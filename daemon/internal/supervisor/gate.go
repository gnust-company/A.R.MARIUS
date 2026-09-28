package supervisor

import "sync"

// Gate is how a daemon stops asking for work and then knows, for certain, that it is idle
// (FR-008n).
//
// The two halves have to be one step. Counting the runs this machine holds and *then* pausing
// the ask loop leaves a gap in which an ask is answered, a run is handed over, and the count that
// said zero is already wrong — a restart decided on it cuts a run that had just arrived. So the
// ask loop asks the gate before every ask (Admit), the gate counts asks in flight, and pausing
// happens only under the same lock that sees no ask in flight and nothing held.
type Gate struct {
	mu       sync.Mutex
	paused   bool
	inFlight int
}

// Admit lets one ask go ahead, unless the gate is paused. The release must be called once the
// ask and everything it was granted have been handed on — ClaimOptions.Admit does exactly that.
func (g *Gate) Admit() (release func(), ok bool) {
	g.mu.Lock()
	defer g.mu.Unlock()
	if g.paused {
		return nil, false
	}
	g.inFlight++
	var once sync.Once
	return func() {
		once.Do(func() {
			g.mu.Lock()
			g.inFlight--
			g.mu.Unlock()
		})
	}, true
}

// PauseIfIdle stops all further asks, but only if no ask is in flight and held reports nothing.
// It answers whether it paused; a gate it did not pause is left exactly as it was.
func (g *Gate) PauseIfIdle(held func() int) bool {
	g.mu.Lock()
	defer g.mu.Unlock()
	if g.paused || g.inFlight > 0 || held() > 0 {
		return false
	}
	g.paused = true
	return true
}

// Resume lets asks go ahead again, after a pause that did not end in a restart.
func (g *Gate) Resume() {
	g.mu.Lock()
	g.paused = false
	g.mu.Unlock()
}
