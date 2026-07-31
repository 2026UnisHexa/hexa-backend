# Hexa Backend

## 음원 저장 설정

Supabase Dashboard의 Storage에서 비공개 버킷 `audio-files`를 생성하고,
로컬 `.env`와 Render 환경변수에 다음 값을 설정합니다.

```text
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service-role-key>
SUPABASE_AUDIO_BUCKET=audio-files
```

`SUPABASE_SERVICE_ROLE_KEY`는 백엔드 전용 비밀키이므로 Git이나 프론트엔드에
넣으면 안 됩니다. `audio_files` 테이블은 Supabase에서 관리합니다.

JWT를 사용하지 않는 데모 구조이므로 API는 `login_id`를 사용자 식별값으로
신뢰합니다.

### WAV 업로드

```bash
curl -X POST http://127.0.0.1:8000/audio \
  -H "Authorization: Bearer <accessToken>" \
  -F "title=봄날" \
  -F "price=1500" \
  -F "genreLabel=발라드" \
  -F "audioFile=@sample.wav;type=audio/wav"
```

`genreLabel`은 선택 항목이며, `created_at`은 업로드 시 DB가 자동으로 기록합니다.

### 사용자 음원 목록

```bash
curl -H "Authorization: Bearer <accessToken>" \
  "http://127.0.0.1:8000/audio"
```

### 음원 재생 또는 다운로드

```text
GET /audio/{audio_id}
```

### 음원 삭제

```text
DELETE /audio/{audio_id}
```
