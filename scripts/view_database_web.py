import os
import sys
import webbrowser
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn
from sqlalchemy import create_engine, text

load_dotenv()

app = FastAPI(title="Canlı Veritabanı Görüntüleyici")

@app.get("/", response_class=HTMLResponse)
def view_records():
    db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres_secure_pass_2026@localhost:5432/audio_db")
    engine = create_engine(db_url)
    
    rows = []
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT id, file_name, status, duration_seconds, sample_rate, language, created_at 
            FROM public.audio_records 
            ORDER BY created_at DESC;
        """)).fetchall()
        rows = result

    html_content = f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <title>PostgreSQL Canlı Veritabanı Görüntüleyici</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #0f172a; color: #f8fafc; padding: 20px; }}
            h1 {{ color: #a78bfa; }}
            .stats {{ background: #1e293b; padding: 15px; border-radius: 8px; margin-bottom: 20px; border: 1px solid #334155; }}
            table {{ width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 8px; overflow: hidden; }}
            th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid #334155; }}
            th {{ background-color: #334155; color: #38bdf8; font-weight: 600; }}
            tr:hover {{ background-color: #334155; }}
            .status-completed {{ background: #065f46; color: #34d399; padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 12px; }}
            .status-pending {{ background: #854d0e; color: #fde047; padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 12px; }}
            .status-failed {{ background: #991b1b; color: #fca5a5; padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 12px; }}
        </style>
    </head>
    <body>
        <h1>📊 PostgreSQL Canlı Veritabanı Görüntüleyici (`audio_db`)</h1>
        <div class="stats">
            <strong>Toplam Kayıt Sayısı:</strong> {len(rows)} Adet | 
            <strong>Baglantı Adresi:</strong> <code>{db_url}</code>
        </div>
        <table>
            <thead>
                <tr>
                    <th>#</th>
                    <th>Dosya Adı</th>
                    <th>Durum</th>
                    <th>Süre (sn)</th>
                    <th>Dil</th>
                    <th>Tarih</th>
                    <th>ID (UUID)</th>
                </tr>
            </thead>
            <tbody>
    """
    
    for idx, r in enumerate(rows, 1):
        status_cls = "status-completed" if r[2] == "COMPLETED" else ("status-pending" if r[2] == "PENDING" else "status-failed")
        dur = f"{r[3]:.1f}s" if r[3] else "-"
        lang = r[5] or "tr"
        html_content += f"""
                <tr>
                    <td>{idx}</td>
                    <td><strong>{r[1]}</strong></td>
                    <td><span class="{status_cls}">{r[2]}</span></td>
                    <td>{dur}</td>
                    <td>{lang}</td>
                    <td>{r[6]}</td>
                    <td><code>{r[0]}</code></td>
                </tr>
        """
        
    html_content += """
            </tbody>
        </table>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

def main():
    print("[+] PostgreSQL Canlı Görüntüleyici Başlatılıyor: http://localhost:8050")
    webbrowser.open("http://localhost:8050")
    uvicorn.run(app, host="127.0.0.1", port=8050, log_level="error")

if __name__ == "__main__":
    main()
