package redact

import (
	"strings"
	"testing"
)

func TestTheRunTokenNeverLeavesTheMachineByAnyChannel(t *testing.T) {
	// Token của lượt chạy đi **vào** agent qua thông điệp và biến môi trường, nên nó ra được
	// bằng đúng hai đường ấy (FR-048a). Bốn kênh, một lượt che.
	token := "armarius_run_9f3c1d8b47ae0025"
	m := For(token, "")

	channels := map[string]string{
		"thông điệp":      "Use " + token + " when calling back.",
		"tham số":         `{"header":"Authorization: Bearer ` + token + `"}`,
		"chữ agent":       "I ran the command with " + token + " and it worked",
		"thông báo lỗi":   "request failed: token " + token + " rejected",
		"biến môi trường": "ARMARIUS_RUN_TOKEN=" + token,
	}
	for channel, text := range channels {
		masked, changed := m.Text(text)
		if !changed {
			t.Errorf("%s: không che gì cả", channel)
		}
		if strings.Contains(masked, token) {
			t.Errorf("%s: token vẫn còn nguyên trong %q", channel, masked)
		}
	}
}

func TestTheMachineTokenIsMaskedTooBecauseItIsWorseToLose(t *testing.T) {
	// Token của **máy** nói thay cho mọi workplace và mọi agent trên nó, còn token lượt chạy
	// mở đúng một lượt. Để lọt cái nặng hơn thì cái nhẹ hơn có che cũng bằng không.
	machine := "armarius_machine_0071ffbc93de"
	m := For("armarius_run_9f3c1d8b47ae0025", machine)

	masked, _ := m.Text("daemon auth " + machine)
	if strings.Contains(masked, machine) {
		t.Fatalf("token của máy lọt ra: %q", masked)
	}
}

func TestASecretThatContainsAnotherIsMaskedWhole(t *testing.T) {
	// Che cái ngắn trước thì cái dài còn lòi đuôi ra — và cái đuôi ấy là phần duy nhất người
	// đoán cần. Nên phải che từ dài xuống ngắn.
	short := "armarius_run_aaaabbbbcccc"
	long := short + "_dddd_eeee"
	m := For(short, long)

	masked, _ := m.Text("token=" + long)
	if strings.Contains(masked, "dddd") {
		t.Fatalf("bí mật dài bị che nửa vời, còn sót đuôi: %q", masked)
	}
}

func TestShapesNobodyDeclaredAreStillCaught(t *testing.T) {
	// Lưới thứ hai: khoá agent đọc được từ một tệp, biến môi trường một công cụ in ra. Không
	// ai khai chúng cho daemon, nên chỉ còn hình dạng để nhận ra.
	m := For()
	// Ghép từng mảnh chứ không viết nguyên văn: mấy chuỗi này là **giả**, nhưng chúng giả
	// đúng dạng thật — nên bộ dò bí mật của kho mã chặn luôn cú push, cùng họ với chính thứ
	// đang được kiểm ở đây. Ghép lúc chạy thì giá trị vẫn y hệt còn tệp thì không mang một
	// chuỗi trông như credential.
	shapes := map[string]string{
		"OpenAI":     "sk" + "-abcdefghijklmnopqrstuvwxyz012345",
		"GitHub":     "ghp" + "_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
		"GitHub PAT": "github" + "_pat_11ABCDEFG0abcdefghijklmnop",
		"Slack":      "xoxb" + "-1234567890-ABCDEFGHIJKLMNOP",
		"AWS":        "AKIA" + "IOSFODNN7EXAMPLE",
		"JWT": "eyJhbGciOiJIUzI1NiJ9." +
			"eyJzdWIiOiIxMjM0NTY3ODkwIn0." +
			"dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk",
	}
	for name, secret := range shapes {
		masked, changed := m.Text("value: " + secret)
		if !changed || strings.Contains(masked, secret) {
			t.Errorf("%s: không nhận ra hình dạng, để lọt %q", name, masked)
		}
	}
}

func TestAPrivateKeyIsTakenOutWholeNotJustItsHeader(t *testing.T) {
	// Che mỗi dòng mở đầu là để lại đúng phần có giá trị.
	m := For()
	key := "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAx7Vk\nQmVhcgo=\n-----END RSA PRIVATE KEY-----"

	masked, changed := m.Text("cat id_rsa\n" + key)
	if !changed {
		t.Fatal("không che gì cả")
	}
	if strings.Contains(masked, "MIIEowIBAAKCAQEAx7Vk") {
		t.Fatalf("thân khoá vẫn còn: %q", masked)
	}
}

func TestAValueNamedAsACredentialIsMaskedWhateverItLooksLike(t *testing.T) {
	// `hunter2` không có hình dạng nào cả. Thứ tố cáo nó là **cái tên đứng cạnh**.
	m := For()
	for _, line := range []string{
		"DATABASE_PASSWORD=hunter2trombone",
		"api_key: 8f4c1a9e2b7d",
		`{"MY_SECRET": "correcthorsebattery"}`,
	} {
		masked, changed := m.Text(line)
		if !changed {
			t.Errorf("không che %q", line)
		}
		for _, leaked := range []string{"hunter2trombone", "8f4c1a9e2b7d", "correcthorsebattery"} {
			if strings.Contains(masked, leaked) {
				t.Errorf("giá trị nhạy cảm lọt ra trong %q", masked)
			}
		}
	}
}

func TestAValueTooShortToBeACredentialIsNeverSearchedFor(t *testing.T) {
	// Ngưỡng 12 ký tự là thứ giữ cho lưới không nuốt cả bản ghi. Hạ nó xuống thì một "abc"
	// nào đó lọt vào danh sách và mọi chữ chứa "abc" thành [redacted] — bản ghi không đọc nổi
	// là bản ghi không ai đọc, tức là mất đúng thứ FR-044 dựng ra.
	//
	// Không có bài kiểm thì ngưỡng ấy đổi được mà không ai thấy, và cái hỏng chỉ lộ ra ở một
	// bản ghi thật của một lượt chạy thật.
	m := For("abc", "run", "0123456789")
	plain := "abc ran the run at 0123456789 and printed abcdef"

	masked, changed := m.Text(plain)
	if changed || masked != plain {
		t.Fatalf("bí mật quá ngắn vẫn bị tìm, chữ bình thường bị che theo: %q", masked)
	}

	// Và ngay trên ngưỡng thì vẫn che, để bài này không xanh chỉ vì `For` bỏ hết mọi thứ.
	long := "armarius_run_x"
	if got, hidden := For(long).Text("token " + long); !hidden || strings.Contains(got, long) {
		t.Fatalf("giá trị đủ dài lại không được che: %q", got)
	}
}

func TestOrdinaryTextIsLeftAloneSoTheLogStaysReadable(t *testing.T) {
	// Một lưới che quá tay biến bản ghi thành giấy vụn, và bản ghi không đọc nổi là bản ghi
	// không ai đọc — tức là mất đúng thứ FR-044 dựng ra.
	m := For("armarius_run_9f3c1d8b47ae0025")
	plain := "Ran 42 tests in 3.5s. All passed. See src/main.go:118 for the change."

	masked, changed := m.Text(plain)
	if changed || masked != plain {
		t.Fatalf("che nhầm chữ bình thường: %q", masked)
	}
}

func TestMaskingWalksIntoNestedArgumentsBecauseThatIsWhereTheyHide(t *testing.T) {
	// FR-043 đòi ghi **đầy đủ tham số**, mà tham số là cây lồng nhau. Một lượt che chỉ nhìn
	// tầng đầu sẽ ghi đầy đủ đúng như đòi hỏi — kèm theo token nằm ở tầng thứ ba.
	token := "armarius_run_9f3c1d8b47ae0025"
	m := For(token)

	payload := map[string]any{
		"name": "http_request",
		"args": map[string]any{
			"url": "https://example.dev",
			"headers": []any{
				map[string]any{"Authorization": "Bearer " + token},
			},
			"retries": 3,
		},
	}
	masked, changed := m.Payload(payload)
	if !changed {
		t.Fatal("không che gì trong tham số lồng nhau")
	}
	deep := masked["args"].(map[string]any)["headers"].([]any)[0].(map[string]any)
	if got := deep["Authorization"].(string); strings.Contains(got, token) {
		t.Fatalf("token nằm ở tầng thứ ba vẫn đi ra: %q", got)
	}
	if masked["args"].(map[string]any)["retries"] != 3 {
		t.Fatal("che làm hỏng giá trị không phải chữ")
	}
}

func TestAPayloadWithNothingToTakeComesBackUntouched(t *testing.T) {
	// `redacted` là một cột trên bản ghi, nên "có che" phải là sự thật chứ không phải mặc định.
	m := For("armarius_run_9f3c1d8b47ae0025")
	payload := map[string]any{"call": "toolu_01", "failed": false}

	masked, changed := m.Payload(payload)
	if changed {
		t.Fatal("báo là đã che trong khi không có gì để che")
	}
	if len(masked) != 2 {
		t.Fatalf("payload bị dựng lại thừa thiếu: %+v", masked)
	}
}

func TestAMaskerToldNothingStillMasksByShape(t *testing.T) {
	// Không có credential nào để khai thì mất bảo đảm, không mất cả lưới.
	var m *Masker
	masked, changed := m.Text("key sk-abcdefghijklmnopqrstuvwxyz012345")
	if !changed || strings.Contains(masked, "sk-abcdefg") {
		t.Fatalf("masker rỗng bỏ qua cả hình dạng: %q", masked)
	}
}

func TestWindowLooksPastTheCutFarEnoughToSeeASecretWhole(t *testing.T) {
	// Bí mật bắt đầu **trước** chỗ cắt và kéo dài qua nó. Nếu chỉ nhìn đúng phần sẽ đi ra thì
	// masker thấy một mẩu token cụt, không khớp gì cả, và mẩu ấy đi ra nguyên.
	token := "armarius_run_9f3c1d8b47ae0025"
	m := For(token)
	body := strings.Repeat("y", 500) + token + strings.Repeat("z", 5000)

	got, hidden := m.Window(body, 512)

	if !hidden {
		t.Fatal("bí mật vắt ngang chỗ cắt không được nhận ra")
	}
	if strings.Contains(got, "armarius_run_9f3c") {
		t.Fatalf("nửa đầu token còn nguyên: %q", got[490:])
	}
}

func TestWindowIgnoresWhatIsOnlyEverGoingToBeThrownAway(t *testing.T) {
	// Đây là chỗ *bảo đảm* và *chi phí* gặp nhau. Phần đuôi không rời khỏi máy, nên che nó
	// không bảo vệ được gì — mà che nó lại là công việc tỉ lệ với thứ công cụ in ra, chạy trên
	// đúng goroutine đang đọc CLI.
	//
	// Quan sát được: `hidden` phải nói về **thứ người ta sắp nhìn thấy**, không phải về việc
	// có một bí mật ở đâu đó trong thứ họ sẽ không bao giờ thấy. Một bản cài che cả thân sẽ
	// báo `true` ở đây, và bài này đỏ.
	token := "armarius_run_9f3c1d8b47ae0025"
	m := For(token)
	body := strings.Repeat("y", 100_000) + token

	got, hidden := m.Window(body, 512)

	if hidden {
		t.Fatal("báo là đã che, trong khi thứ bị che nằm ngoài tầm nhìn của người đọc")
	}
	if len(got) > 512+m.reach() {
		t.Fatalf("nhìn xa hơn mức cần: %d bytes", len(got))
	}
}

func TestAPrivateKeyWhoseFooterFellBeyondTheCutIsStillTakenOut(t *testing.T) {
	// Mẫu PEM có trần độ dài, nên một khoá bị cắt mất dòng đóng sẽ không khớp mẫu đủ cặp —
	// và phần lọt lại chính là thân khoá, tức là đúng phần đáng ăn cắp.
	m := For()
	key := "-----BEGIN RSA PRIVATE KEY-----\n" + strings.Repeat("MIIEowIBAAKCAQEAx7Vk", 200) +
		"\n-----END RSA PRIVATE KEY-----"

	got, hidden := m.Window("cat id_rsa\n"+key, 512)

	if !hidden {
		t.Fatal("khoá bị cắt mất dòng đóng thì không che gì cả")
	}
	if strings.Contains(got, "MIIEowIBAAKCAQEAx7Vk") {
		t.Fatalf("thân khoá đi ra theo phần đầu: %q", got)
	}
}
