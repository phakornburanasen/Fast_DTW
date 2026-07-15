# วิธี Build เป็น .exe

## ขั้นตอน

### 1. ติดตั้ง PyInstaller (ครั้งแรกครั้งเดียว)
```
pip install pyinstaller
```

### 2. Build
```
build.bat
```
หรือรันตรงๆ:
```
pyinstaller tf_generator.spec --clean --noconfirm
```

### 3. ผลลัพธ์
ไฟล์ที่ได้อยู่ที่:
```
dist\tf_generator.exe
```

---

## วิธีรัน .exe

```
dist\tf_generator.exe
```

Server จะรัน **4 workers** บน `http://0.0.0.0:60000`  
เข้าถึงได้จาก IP เครื่องอื่นใน network เช่น `http://10.115.2.61:60000`

Console จะแสดง:
```
[tf_generator] Starting 4 workers on http://0.0.0.0:60000
[tf_generator] Worker 1 started (pid=1234)
[tf_generator] Worker 2 started (pid=1235)
[tf_generator] Worker 3 started (pid=1236)
[tf_generator] Worker 4 started (pid=1237)
```

กด `Ctrl+C` เพื่อหยุดทุก worker

---

## โครงสร้างที่ได้

```
dist\
  tf_generator.exe   ← single executable ไฟล์เดียว
```

---

## หมายเหตุ

- Build ต้องทำบน **Windows** (เพราะใช้ `subprocess.CREATE_NEW_CONSOLE` และ path `C:\tnl_appl\...`)
- ไฟล์ output (`TF_Head.txt`, `TF_Detail.txt`) ยังคงถูก save ที่ `C:\tnl_appl\support_b1\Template\` ตามเดิม
- ถ้าต้องการเปลี่ยน `OUTPUT_DIR` หรือ `port` ให้แก้ใน `config.py` / `main.py` แล้ว build ใหม่
- `dist\` และ `build\` folder ถูก generate โดย PyInstaller ไม่ต้อง commit เข้า git
