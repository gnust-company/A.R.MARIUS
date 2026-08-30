package runtime

import (
	"testing"

	"github.com/gnust-company/armarius-daemon/internal/discovery"
)

// TestTheFlagAValueWasReadFromIsTheFlagItIsSpentOn canh **mối nối** giữa hai bảng.
//
// Hai bảng, hai package, cùng một sự thật: bên dò đọc dải giá trị **ra khỏi** một cái cờ, bên
// chạy tiêu giá trị ấy **vào** một cái cờ. Mỗi bảng đúng riêng nó thì không nói lên gì cả —
// đổi tên một bên và không đổi bên kia thì **không có gì hỏng**: người dùng vẫn chọn được,
// giá trị vẫn đi xuống máy, và nó áp vào đúng con số không. Màn hình trông đúng suốt cả quãng.
//
// Đây đúng loại lỗ đã bắt được hai lần ở đợt này (hai mã lượt chạy khai mà không đặt; chương
// trình gọi ngược đóng gói mà không đặt vào máy), nên lần này bài kiểm bắc qua khe trước.
func TestTheFlagAValueWasReadFromIsTheFlagItIsSpentOn(t *testing.T) {
	for cli, shape := range oneShots {
		read := discovery.FlagRead(discovery.Kind(cli))
		if len(read) == 0 && len(shape.flags) == 0 {
			continue
		}
		for key, from := range read {
			spentOn, spends := shape.flags[key]
			if !spends {
				t.Errorf(
					"%s: phép dò bày ra %q cho người dùng chọn, nhưng lúc chạy không có cờ nào tiêu nó",
					cli, key,
				)
				continue
			}
			if spentOn != from {
				t.Errorf(
					"%s: %q đọc dải giá trị ra từ %q nhưng lại tiêu vào %q — người dùng chọn xong áp vào hư không",
					cli, key, from, spentOn,
				)
			}
		}
		for key := range shape.flags {
			if _, offered := read[key]; !offered {
				t.Errorf(
					"%s: lúc chạy tiêu %q nhưng phép dò không bao giờ bày nó ra — một thiết lập không ai chọn được",
					cli, key,
				)
			}
		}
	}
}
