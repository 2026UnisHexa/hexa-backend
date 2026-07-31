# Hexa Backend

## 실행

1. `.env`의 `[YOUR-PASSWORD]`, `[PROJECT-REF]`를 실제 Supabase 값으로 변경합니다.
2. 가상환경을 활성화하고 의존성을 설치합니다.

```bash
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

서버 확인: <http://127.0.0.1:8000/>

DB 연결 확인: <http://127.0.0.1:8000/health/db>

## 회원가입 / 로그인

회원가입 요청(아이디는 영문·숫자·`_`·`-`만 허용, 비밀번호는 8자 이상):

```bash
curl -X POST http://127.0.0.1:8000/signup \
  -H "Content-Type: application/json" \
  -d '{"login_id":"new_user","password":"password123"}'
```

로그인 요청:

```bash
curl -X POST http://127.0.0.1:8000/login \
  -H "Content-Type: application/json" \
  -d '{"login_id":"new_user","password":"password123"}'
```

현재 로그인 API는 자격 증명 확인 결과만 반환하며 로그인 상태를 유지하지 않습니다.

## 더미 사용자 생성

`.env`에 실제 Supabase 연결 문자열을 입력한 다음 실행합니다.

```bash
python seed_users.py
```

`hexa01`부터 `hexa05`까지 생성되며 비밀번호는 각각 `test01`부터
`test05`까지입니다. 비밀번호는 Argon2로 해시되어 `password_hash`에
저장되고, 이미 존재하는 `login_id`는 건너뜁니다.

Supabase의 direct connection이 IPv6 환경 문제로 연결되지 않으면 Dashboard에 표시되는 Session pooler 연결 문자열을 `.env`에 사용하세요. 연결 문자열의 앞부분은 `postgresql+psycopg://`로 맞춰야 합니다.
