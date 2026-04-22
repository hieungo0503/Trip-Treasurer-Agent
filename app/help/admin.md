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

   /trips            Danh sách chuyến
   /trip_view <id>   Xem chi tiết
   /trip_switch <id> Đổi chuyến active
   /trip_end         Kết chuyến +
                     settlement
   /trip_archive     Lưu trữ chuyến cũ

🛠 SỬA DỮ LIỆU:
   /huy_auto <id>    Huỷ auto-advance
   /rebuild_sheet    Ghi lại Sheet từ DB

⏸ ĐIỀU KHIỂN BOT:
   /pause_bot        Tạm dừng bot
   /resume_bot       Bật lại bot

📨 GIỚI THIỆU CHO NHÓM:
   /share    → tin mẫu copy-paste

⚠️ AN TOÀN:
   Mọi lệnh admin đều ghi audit log.
   Bot luôn yêu cầu xác nhận trước
   khi thực hiện thao tác phá huỷ.
