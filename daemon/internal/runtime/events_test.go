package runtime

import (
	"strings"
	"testing"
	"unicode/utf8"
)

func collected() (*Journal, *[]Event) {
	var seen []Event
	journal := NewJournal(Request{Secrets: []string{"armarius_run_9f3c1d8b47ae0025"}}, func(e Event) {
		seen = append(seen, e)
	})
	return journal, &seen
}

func TestAResultThatFitsIsNotMarkedAsCut(t *testing.T) {
	// `truncated` là một khẳng định, không phải mặc định: đánh dấu đã cắt một kết quả nguyên vẹn
	// bảo người đọc đi tìm phần còn lại của một thứ họ đang nhìn trọn vẹn.
	journal, seen := collected()

	journal.ToolCompleted("toolu_1", false, Result{Exposed: true, Body: "127.0.0.1 localhost"})

	got := (*seen)[0]
	if got.Truncated || got.OmissionReason != "" {
		t.Fatalf("kết quả vừa ngưỡng mà báo là thiếu: truncated=%v reason=%q", got.Truncated, got.OmissionReason)
	}
	if got.Payload["opening"] != "127.0.0.1 localhost" {
		t.Fatalf("phần đầu không đủ: %v", got.Payload["opening"])
	}
	if got.Payload["bytes"] != 19 {
		t.Fatalf("kích thước: %v", got.Payload["bytes"])
	}
}

func TestAResultOverTheThresholdKeepsItsTailAtHomeAndSaysHowMuch(t *testing.T) {
	// FR-043b: cắt mà không nói cắt bao nhiêu thì người đọc tưởng đó là toàn bộ kết quả — và
	// một bản ghi làm người đọc tin sai còn tệ hơn một bản ghi thiếu.
	journal, seen := collected()
	whole := strings.Repeat("x", DefaultResultLimit*3)

	journal.ToolCompleted("toolu_1", false, Result{Exposed: true, Body: whole})

	got := (*seen)[0]
	if !got.Truncated {
		t.Fatal("cắt rồi mà không nói")
	}
	if got.OriginalBytes != len(whole) || got.Payload["bytes"] != len(whole) {
		t.Fatalf("kích thước gốc: cột=%d thân=%v, phải là %d", got.OriginalBytes, got.Payload["bytes"], len(whole))
	}
	if opening := got.Payload["opening"].(string); len(opening) > DefaultResultLimit {
		t.Fatalf("phần đầu dài quá ngưỡng: %d bytes", len(opening))
	}
}

func TestTheTwoReasonsForMissingDataAreNotTheSameValue(t *testing.T) {
	// FR-047 nói thẳng: *ta cắt* và *CLI không lộ* là hai chuyện, không được hiện giống nhau.
	// Cái thứ nhất sửa được bằng một ngưỡng; cái thứ hai thì không có ngưỡng nào chạm tới.
	journal, seen := collected()

	journal.ToolCompleted("cut", false, Result{Exposed: true, Body: strings.Repeat("x", DefaultResultLimit*2)})
	journal.ToolCompleted("silent", false, Result{Exposed: false})

	cut, silent := (*seen)[0], (*seen)[1]
	if cut.OmissionReason != TruncatedByPolicy {
		t.Fatalf("bị cắt phải nói là bị cắt: %q", cut.OmissionReason)
	}
	if silent.OmissionReason != NotExposedByCLI {
		t.Fatalf("CLI không lộ phải nói đúng thế: %q", silent.OmissionReason)
	}
	if cut.OmissionReason == silent.OmissionReason {
		t.Fatal("hai lý do khác nhau đang hiện giống nhau")
	}
}

func TestACLIThatRevealsNothingLeavesNoGapPretendingToBeAnEmptyResult(t *testing.T) {
	// Khoảng trống trông y như *công cụ trả về rỗng*. Đánh dấu là cách duy nhất để người đọc
	// biết chỗ ấy có dữ liệu mà máy này không được thấy.
	journal, seen := collected()

	journal.ToolCompleted("toolu_1", false, Result{Exposed: false})

	got := (*seen)[0]
	if got.Truncated {
		t.Fatal("không có gì để cắt mà báo là đã cắt")
	}
	if _, present := got.Payload["opening"]; present {
		t.Fatalf("dựng ra phần đầu từ thứ chưa từng nhận được: %v", got.Payload)
	}
	if _, present := got.Payload["bytes"]; present {
		t.Fatalf("dựng ra một kích thước không ai đo: %v", got.Payload)
	}
}

func TestASecretLyingAcrossTheCutIsMaskedRatherThanHalved(t *testing.T) {
	// Cắt trước rồi che thì nửa đầu token đã nằm trong phần đi ra, và che nửa sau không lấy lại
	// được gì. Nên phải che trước, cắt sau.
	token := "armarius_run_9f3c1d8b47ae0025"
	journal, seen := collected()
	body := strings.Repeat("y", DefaultResultLimit-10) + token + strings.Repeat("z", 100)

	journal.ToolCompleted("toolu_1", false, Result{Exposed: true, Body: body})

	got := (*seen)[0]
	opening := got.Payload["opening"].(string)
	if strings.Contains(opening, "armarius_run_9f3c") {
		t.Fatalf("nửa đầu token đi ra theo phần đầu kết quả: %q", opening)
	}
	if !got.Redacted {
		t.Fatal("che rồi mà không ghi lại là đã che")
	}
}

func TestTheThresholdIsSettableBecauseTheSpecSaysSo(t *testing.T) {
	var seen []Event
	journal := NewJournal(Request{ResultLimit: 8}, func(e Event) { seen = append(seen, e) })

	journal.ToolCompleted("toolu_1", false, Result{Exposed: true, Body: "0123456789abcdef"})

	if opening := seen[0].Payload["opening"].(string); len(opening) != 8 {
		t.Fatalf("ngưỡng đặt riêng không có tác dụng: %q", opening)
	}
}

func TestTheCutFallsOnACharacterBoundaryNotAByteOne(t *testing.T) {
	// Cắt giữa một ký tự nhiều byte thì phần đuôi lên màn thành ô vuông — đọc ra *công cụ in ra
	// thứ gì lạ*, chứ không phải *chỗ này bị cắt*.
	var seen []Event
	journal := NewJournal(Request{ResultLimit: 4}, func(e Event) { seen = append(seen, e) })

	journal.ToolCompleted("toolu_1", false, Result{Exposed: true, Body: "một hai ba"})

	opening := seen[0].Payload["opening"].(string)
	if !utf8.ValidString(opening) {
		t.Fatalf("cắt vỡ ký tự: %q", opening)
	}
}

func TestEverythingTheAgentSaysGoesThroughTheSameGate(t *testing.T) {
	// FR-048a: che áp cho **mọi** kênh. Một kênh quên đi qua cổng là một kênh không có gì chặn,
	// và nó trông y hệt một kênh không có gì để chặn.
	token := "armarius_run_9f3c1d8b47ae0025"
	journal, seen := collected()

	journal.Text("I called back with " + token)
	journal.Thought("the token " + token + " should work")
	journal.ToolStarted("c1", "http", map[string]any{"auth": "Bearer " + token}, true)
	journal.Fail("agent_reported_failure", map[string]any{"why": "rejected " + token})

	for _, event := range *seen {
		if !event.Redacted {
			t.Errorf("%s: không che gì cả", event.Type)
		}
		for key, value := range event.Payload {
			if text, isText := value.(string); isText && strings.Contains(text, token) {
				t.Errorf("%s: token đi ra ở %q", event.Type, key)
			}
		}
	}
	if len(*seen) != 4 {
		t.Fatalf("số sự kiện: %d", len(*seen))
	}
}

func TestAnEventWithNothingToHideIsNotMarkedAsRedacted(t *testing.T) {
	journal, seen := collected()

	journal.Text("all tests passed")

	if (*seen)[0].Redacted {
		t.Fatal("báo là đã che trong khi không có gì để che")
	}
}

func TestArgumentsACLIDoesNotRevealAreMarkedRatherThanSentEmpty(t *testing.T) {
	// Một map rỗng đọc ra *gọi công cụ mà không truyền gì* — một sự thật khác hẳn, và nó làm
	// CLI trông cẩu thả hơn nó thật (FR-047).
	journal, seen := collected()

	journal.ToolStarted("c1", "search", nil, false)

	got := (*seen)[0]
	if _, present := got.Payload["args"]; present {
		t.Fatalf("dựng ra tham số rỗng: %v", got.Payload)
	}
	if got.OmissionReason != NotExposedByCLI {
		t.Fatalf("lý do thiếu tham số: %q", got.OmissionReason)
	}
}

func TestSayingNothingIsNotAnEvent(t *testing.T) {
	// Chữ rỗng từ một chunk trống là chuyện thường ở cả hai họ; ghi nó ra là đẻ ra một bọt rỗng
	// trên màn cho mỗi lần CLI thở.
	journal, seen := collected()

	journal.Text("")
	journal.Thought("")

	if len(*seen) != 0 {
		t.Fatalf("ghi ra sự kiện rỗng: %+v", *seen)
	}
}
