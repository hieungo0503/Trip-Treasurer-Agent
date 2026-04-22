# Help Content — Trip Treasurer Bot

**Phiên bản:** 2.2
**Vai trò:** Nội dung đầy đủ của 9 file markdown đặt trong `app/help/` của repo.

Bot load file này lúc chạy và gửi nội dung qua Zalo khi user gõ lệnh help tương ứng.

**Quy tắc format:**
- Mỗi file giới hạn ~40-50 dòng (fit 1 màn hình Zalo)
- Dùng emoji để dễ scan
- Luôn có ví dụ cú pháp cụ thể, không chỉ mô tả trừu tượng
- Không dùng bảng markdown phức tạp (Zalo không render markdown), dùng text thuần với khung ┌─┐

---

## 1. `app/help/overview.md`

Trigger: `/help`, `/lenh`, `/menu`, `/commands`, "hướng dẫn", "cách dùng", "làm sao", "không biết", "help"

```
🤖 TRIP TREASURER — THỦ QUỸ SỐ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Bot này giúp cả nhóm quản lý chi
tiêu chuyến đi, tự chia tiền công
bằng, không cần tính toán cuối chuyến.

📌 4 THAO TÁC CHÍNH:

1️⃣ GHI CHI TIÊU
   "chi 500k đồ ăn"
   "trả 200k grab"
   (gửi ảnh bill cũng được)

2️⃣ NẠP THÊM VÀO QUỸ
   "nạp 500k" / "góp 500k"

3️⃣ ỨNG TIỀN (khi quỹ không đủ)
   "ứng 1tr để chi thuyền"

4️⃣ XEM THÔNG TIN
   /quy      — xem quỹ hiện tại
   /tongket  — tổng kết chuyến
   /cuatoi   — khoản chi của tôi
   /chiaai   — đề xuất chia tiền

💡 XEM CHI TIẾT TỪNG CHỦ ĐỀ:
   /help chi      — cách ghi chi tiêu
   /help nap      — cách nạp quỹ
   /help ung      — cách ứng tiền
   /help anh      — cách gửi ảnh bill
   /help admin    — lệnh admin
   /help chiatien — cách chia tiền

📨 MUỐN GIỚI THIỆU BOT CHO NHÓM:
   /share  → bot sẽ gửi tin mẫu để
            bạn copy vào group Zalo
```

---

## 2. `app/help/chi.md`

Trigger: `/help chi`

```
📖 HƯỚNG DẪN: GHI CHI TIÊU
━━━━━━━━━━━━━━━━━━━━━━━━━━
📝 CÚ PHÁP:
   "chi <số tiền> <nội dung>"
   "trả <số tiền> <nội dung>"

💡 VÍ DỤ:
   ✓ chi 500k mua đồ nướng
   ✓ trả 200k grab
   ✓ 1tr5 khách sạn
   ✓ taxi 150k

🔢 CÁCH VIẾT SỐ TIỀN:
   • 500k         = 500.000đ
   • 1tr / 1triệu = 1.000.000đ
   • 1tr5 / 1.5tr = 1.500.000đ
   • 500.000      = 500.000đ
   • 500000       = 500.000đ

🔄 LUỒNG XÁC NHẬN:
   1. Bạn gõ khoản chi
   2. Bot gửi card tóm tắt
   3. Bạn "ok" / "sửa ..." / "huỷ"
   4. Bot ghi vào quỹ, báo kết quả

⚠️ NẾU QUỸ KHÔNG ĐỦ:
   Bot sẽ hỏi có ứng tự động không.
   Xem thêm: /help ung

🔗 Xem thêm:
   /help anh      — gửi ảnh bill
   /help chiatien — cách chia tiền
```

---

## 3. `app/help/nap.md`

Trigger: `/help nap`

```
📖 HƯỚNG DẪN: NẠP QUỸ
━━━━━━━━━━━━━━━━━━━━━━━━━━
Có 2 loại nạp quỹ:

1️⃣ NẠP ĐẦU CHUYẾN
   Khi chuyến vừa tạo, mỗi người nạp
   số tiền mà admin yêu cầu.

   📝 Cú pháp:
      "<tên> đã nạp <số tiền>"
      "<tên> góp <số tiền>"

   💡 Ví dụ:
      ✓ Hà đã nạp 1tr
      ✓ Long góp 1 triệu
      ✓ Minh đã nạp 1tr vào quỹ

2️⃣ NẠP THÊM (bất cứ lúc nào)
   Khi quỹ sắp hết, muốn nạp thêm
   cho cả nhóm dùng tiếp.

   📝 Cú pháp:
      "nạp <số tiền>"
      "góp <số tiền>"

   💡 Ví dụ:
      ✓ nạp 500k
      ✓ góp thêm 1tr vào quỹ

🔄 Sau khi gõ, bot sẽ gửi card xác
   nhận, bạn "ok" để ghi.

⚠️ KHÁC BIỆT VỚI "ỨNG":
   • Nạp → tiền vào quỹ, dùng sau
   • Ứng → tiền chi ngay, không qua
          quỹ. Xem: /help ung
```

---

## 4. `app/help/ung.md`

Trigger: `/help ung`

```
📖 HƯỚNG DẪN: ỨNG TIỀN
━━━━━━━━━━━━━━━━━━━━━━━━━━
Ứng = bạn bỏ tiền túi trả trực tiếp,
không rút từ quỹ chung.

🎯 KHI NÀO DÙNG?
   Khi quỹ không đủ, bạn chủ động
   trả luôn bằng tiền riêng để không
   bị trễ việc.

📝 CÚ PHÁP:
   "ứng <số tiền> để chi <nội dung>"
   "ứng <số tiền> để trả <nội dung>"

💡 VÍ DỤ:
   ✓ ứng 1tr để chi thuê thuyền
   ✓ ứng 500k để trả taxi
   ✓ ứng 800k trả bữa tối

📋 BOT SẼ GHI 2 RECORD LIÊN KẾT:
   • Bạn ứng:    <số tiền>
   • Chi khoản:  <số tiền>
   → Quỹ KHÔNG thay đổi
   → Cuối chuyến bạn được hoàn

⚠️ KHÁC BIỆT AUTO-ADVANCE:
   Nếu bạn chỉ gõ "chi X" mà quỹ
   không đủ, bot sẽ hỏi có ứng tự
   động không. Dùng "ứng ... để chi"
   là khai rõ ràng ngay từ đầu,
   không cần bot hỏi thêm.

🔧 LỠ GHI SAI?
   Dùng /huy_auto <expense_id> để
   huỷ nếu bot tự động ứng nhầm.
```

---

## 5. `app/help/anh.md`

Trigger: `/help anh`

```
📖 HƯỚNG DẪN: GỬI ẢNH BILL
━━━━━━━━━━━━━━━━━━━━━━━━━━
📸 CÁCH DÙNG:
   Chụp bill/hoá đơn rõ ràng, gửi
   vào chat với bot. Không cần gõ
   thêm gì, bot tự nhận diện.

✅ BOT SẼ TỰ TRÍCH XUẤT:
   • Tổng số tiền
   • Tên cửa hàng / mô tả
   • Thời gian

👤 AI LÀ NGƯỜI CHI?
   Mặc định: bạn (người gửi ảnh).

   Nếu người chi thực là người khác:
   Gõ: "sửa nguoichi <tên>"
   (trong khi đang xác nhận)

💡 MẸO CHỤP BILL:
   ✓ Đủ sáng, không bị bóng
   ✓ Thẳng, không xéo
   ✓ Rõ phần tổng tiền
   ✓ 1 bill / 1 ảnh (chưa hỗ trợ
     nhiều bill cùng lúc)

⚠️ ĐỘ TIN CẬY:
   Bot hiện tỷ lệ tin cậy OCR
   trong card xác nhận. Nếu < 60%
   sẽ đề nghị bạn nhập tay thay vì
   dùng kết quả OCR.

🔗 Sau OCR, luồng giống "chi":
   /help chi
```

---

## 6. `app/help/admin.md`

Trigger: `/help admin`

```
📖 HƯỚNG DẪN: LỆNH ADMIN
━━━━━━━━━━━━━━━━━━━━━━━━━━
Chỉ dành cho admin chuyến (người tạo).

🧳 TẠO & QUẢN LÝ CHUYẾN:
   /trip_new <tên>, <thời gian>,
            <số người> gồm <tên ds>,
            <nạp đầu>/người

   VD: /trip_new Hạ Long, 15-18/04,
       4 người gồm đức hà long minh,
       1tr/người

   /trip_status      Xem tiến độ nạp
   /trip_remind      Nhắc người chưa nạp
   /trip_addmember <tên> <nạp>
                     Thêm member mới
   /trip_removemember <tên>
                     Bớt member
   /trip_cancel      Huỷ chuyến
                     (khi chưa active)
   /trip_end         Kết chuyến, chạy
                     settlement

🛠 SỬA DỮ LIỆU:
   /huy <expense_id>     Xoá expense
                         bất kỳ
   /rebuild_sheet        Ghi lại Sheet
                         từ DB

📨 GIỚI THIỆU CHO NHÓM:
   /share    → tin mẫu copy-paste

⚠️ AN TOÀN:
   Mọi lệnh admin đều ghi audit log.
   Bot luôn yêu cầu xác nhận trước
   khi thực hiện thao tác phá huỷ.
```

---

## 7. `app/help/chiatien.md`

Trigger: `/help chiatien`

```
📖 HƯỚNG DẪN: CÁCH CHIA TIỀN
━━━━━━━━━━━━━━━━━━━━━━━━━━
Bot chia tiền công bằng tự động.
Bạn không phải tính toán thủ công.

💡 NGUYÊN TẮC CƠ BẢN:
   Mỗi khoản chi được chia đều
   cho cả nhóm (mặc định).

📊 VỊ THẾ CỦA MỖI NGƯỜI:
   • Contribution: tiền bạn đã nạp
                   + tiền ứng (nếu có)
   • Fair share:   phần bạn phải gánh
                   (= tổng chi / N người)
   • Net:          contribution − fair_share
     + > 0: được hoàn lại
     − < 0: phải trả thêm

🧮 VÍ DỤ:
   4 người nạp đầu 1tr/người.
   Tổng chi chuyến: 3.2tr
   Fair share: 800k/người

   Ai chi nhiều hơn 800k → được hoàn
   Ai chi ít hơn 800k → phải trả bù

🎯 XEM KẾT QUẢ:
   /quy       Quỹ hiện tại
   /tongket   Tổng kết đầy đủ
   /cuatoi    Khoản chi của tôi
   /nap_cua_toi  Lịch sử nạp của tôi
   /chiaai    Đề xuất chia tiền

💰 KẾT CHUYẾN:
   Admin gõ /trip_end → bot đưa ra
   đề xuất chia tiền với số giao
   dịch ít nhất, các bạn chuyển
   khoản cho nhau theo gợi ý.
```

---

## 8. `app/help/share.md`

Trigger: `/share`

```
📨 TIN GIỚI THIỆU CHO NHÓM
━━━━━━━━━━━━━━━━━━━━━━━━━━
Sao chép tin dưới đây và gửi vào
group chat Zalo của nhóm bạn:

┌──────────────────────────────────┐
│ 🧳 Mọi người ơi, nhóm mình sẽ    │
│ dùng bot để quản lý chi tiêu     │
│ chuyến đi cho tiện.              │
│                                  │
│ 👉 BƯỚC 1: Search OA             │
│    "Trip Treasurer" trên Zalo    │
│    và bấm Quan tâm.              │
│                                  │
│ 👉 BƯỚC 2: Nhắn riêng cho bot:   │
│    "<tên của bạn> đã nạp <số>"   │
│    VD: Hà đã nạp 1tr             │
│                                  │
│ 👉 BƯỚC 3: Khi đi chơi, mỗi lần  │
│    chi tiền thì nhắn bot:        │
│    "chi <số tiền> <nội dung>"    │
│    VD: chi 500k đồ nướng         │
│    Hoặc gửi ảnh bill cũng được.  │
│                                  │
│ Bot sẽ tự chia tiền công bằng    │
│ cuối chuyến. Không biết gì gõ    │
│ /help hoặc "hướng dẫn" cho bot.  │
└──────────────────────────────────┘

💡 SAU KHI GỬI TIN NÀY:
   • Bot sẽ welcome từng member khi
     họ nhắn lần đầu
   • Bot hướng dẫn cụ thể cho từng
     người
   • Bạn (admin) chỉ cần /trip_status
     để xem tiến độ

📖 Gõ /help nếu cần nhắc lại.
```

---

## 9. `app/help/welcome.md`

Trigger: Tự động khi user mới follow OA hoặc nhắn lần đầu không hợp lệ.

```
👋 CHÀO MỪNG ĐẾN TRIP TREASURER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Mình là bot giúp nhóm bạn quản lý
chi tiêu chuyến đi — tự chia tiền
công bằng, không cần tính toán.

Bạn có 2 trường hợp:

1️⃣ BẠN ĐƯỢC MỜI VÀO CHUYẾN
   (admin đã tạo sẵn)

   Nhắn theo cú pháp:
   "<tên của bạn> đã nạp <số tiền>"

   💡 VÍ DỤ:
      ✓ Hà đã nạp 1tr
      ✓ Long góp 1 triệu

   Bot sẽ kiểm tra tên bạn có trong
   danh sách admin khai không, rồi
   gửi card xác nhận.

2️⃣ BẠN MUỐN TẠO CHUYẾN MỚI
   (bạn làm admin)

   Gõ:
   /trip_new <tên>, <thời gian>,
             <số người> gồm <danh sách>,
             <nạp đầu>/người

   💡 VÍ DỤ:
      /trip_new Đà Lạt, 10-12/05,
      3 người gồm an bình chi, 500k

   Bot sẽ hướng dẫn các bước tiếp.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📖 XEM CHI TIẾT: /help
💬 KHÔNG BIẾT GÕ GÌ? Gõ "hướng dẫn"
   bot sẽ gợi ý.
```

---

## 10. Bonus — file `app/help/syntax_suggestion.md` (internal)

Không trigger trực tiếp. Dùng khi user gõ mơ hồ có số tiền nhưng không match intent nào.

```
🤔 BOT CHƯA RÕ Ý BẠN

Có phải bạn muốn GHI CHI TIÊU?
Thử gõ:
   "chi <số tiền> <nội dung>"

💡 VÍ DỤ GẦN VỚI TIN CỦA BẠN:
   {bot tự gợi ý ví dụ
    dựa trên số tiền detect được,
    VD: "chi 500k tiền ăn"}

🔄 HOẶC BẠN ĐANG MUỐN:
   • Nạp quỹ?       → "nạp 500k"
   • Ứng tiền?      → "ứng 500k để chi ..."
   • Xem quỹ?       → /quy
   • Hướng dẫn?     → /help
```

Logic gợi ý trong code:

```python
def suggest_syntax(text: str) -> str:
    money = extract_money(text)
    tpl = load_template('syntax_suggestion.md')
    if money:
        example = f'"chi {format_money(money)} {extract_context(text)}"'
    else:
        example = '"chi 500k tiền ăn"'
    return tpl.format(example=example)
```

---

## Quy tắc vận hành

### Khi nào update help content?

- Thêm intent mới → update `overview.md` + tạo topic file mới
- Đổi cú pháp parse → update file liên quan (đổi ví dụ)
- Nhận feedback user "bot hướng dẫn khó hiểu" → rewrite rõ hơn

### Cách version control

- Help content nằm trong repo, version theo git
- Không cần migration DB khi sửa help (file markdown thuần)
- Có thể A/B test 2 phiên bản help bằng cách đặt `overview_v2.md` và bật flag

### i18n (tương lai)

Cấu trúc sẵn sàng cho tiếng Anh:

```
app/help/
├── vi/    # tiếng Việt (mặc định)
│   ├── overview.md
│   └── ...
├── en/    # English (sau)
│   ├── overview.md
│   └── ...
```

Loader: `load_help(topic, lang='vi')`.

---

**Hết HELP_CONTENT.**

Ghép với [PLAN_v2.2.md](./PLAN_v2.2.md) để có bức tranh đầy đủ. Phase 1 sẽ implement đầy đủ 9 file này vào `app/help/`.
