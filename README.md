# TravelLog

旅行管理アプリ（Flask + Supabase + Google Maps API）

## 必要な環境変数

- `SUPABASE_URL`
- `SUPABASE_KEY`
- `SUPABASE_BUCKET` (任意。画像アップロード先のバケット名。既定: `place-photos`)
- `GOOGLE_MAPS_API_KEY`
- `SECRET_KEY` (任意。Flask セッション用)

## データベース

このアプリ専用の新規テーブルを使用します。`db_schema.sql` を Supabase で実行してください。

## 起動

```bash
python app.py
```
"# TravelLog" 
