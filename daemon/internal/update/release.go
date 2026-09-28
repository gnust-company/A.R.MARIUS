package update

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"path"
	"strings"
	"time"
)

// DefaultReleases is where releases of this daemon are published — the same page `install.sh`
// reads (FR-008i).
const DefaultReleases = "https://github.com/gnust-company/A.R.MARIUS/releases"

// maxDownload bounds one download. A release archive is tens of megabytes; a response far past
// that is not a release, and reading it to the end would be letting a misbehaving server decide
// how much of this machine's memory it gets.
const maxDownload = 256 << 20

// Releases is the place releases are read from.
type Releases struct {
	// Base is the releases page: `<Base>/latest` and `<Base>/download/<tag>/<file>`.
	Base string
	// Client is what talks to it. It must not follow redirects on its own for Latest to work,
	// which is why the zero value builds its own rather than borrowing http.DefaultClient.
	Client *http.Client
}

func (r Releases) withDefaults() Releases {
	if r.Base == "" {
		r.Base = DefaultReleases
	}
	r.Base = strings.TrimSuffix(r.Base, "/")
	if r.Client == nil {
		r.Client = &http.Client{Timeout: 5 * time.Minute}
	}
	return r
}

// Latest is the tag of the newest release, read off the redirect `/latest` answers with.
//
// The redirect rather than the API, for the reason the installer gives: no token, and no rate
// limit on a machine that asks every six hours for as long as it runs.
func (r Releases) Latest(ctx context.Context) (string, error) {
	r = r.withDefaults()
	client := *r.Client
	client.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, r.Base+"/latest", nil)
	if err != nil {
		return "", err
	}
	resp, err := client.Do(req)
	if err != nil {
		return "", fmt.Errorf("asking for the latest release: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 64<<10))

	if resp.StatusCode < 300 || resp.StatusCode >= 400 {
		return "", fmt.Errorf("asking for the latest release: %s answered %s rather than a redirect",
			r.Base+"/latest", resp.Status)
	}
	location, err := resp.Location()
	if err != nil {
		return "", fmt.Errorf("asking for the latest release: the redirect names no place: %w", err)
	}
	// `…/releases/tag/v0.1.0`. A redirect anywhere else — to the releases list, when there is no
	// release at all — names no tag, and saying so beats reading `releases` as a version.
	tag := path.Base(location.Path)
	if path.Base(path.Dir(location.Path)) != "tag" || tag == "" {
		return "", errors.New("asking for the latest release: there is no published release yet")
	}
	return tag, nil
}

// Download fetches one file published with a release.
func (r Releases) Download(ctx context.Context, tag, name string) ([]byte, error) {
	r = r.withDefaults()
	url := r.Base + "/download/" + tag + "/" + name
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	resp, err := r.Client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("downloading %s: %w", name, err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("downloading %s: %s answered %s", name, url, resp.Status)
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxDownload+1))
	if err != nil {
		return nil, fmt.Errorf("downloading %s: %w", name, err)
	}
	if len(body) > maxDownload {
		return nil, fmt.Errorf("downloading %s: larger than %d bytes, which no release is", name, maxDownload)
	}
	return body, nil
}
