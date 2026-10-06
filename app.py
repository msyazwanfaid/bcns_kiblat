"""
Aplikasi Kiblat Selari Bayang Matahari 5 Hari - Balai Cerap Negeri Sembilan
- Carian Lokasi Geocoding OpenStreetMap
- Peta Folium (FOV 100m, Garis 2 km, Fixed Zoom)
- Analisis Suria Tetap 5 Hari (falakpy)
- Penjana PDF Bersijil & Muat Turun Kod QR
- Sistem Keep-Alive Automatik (Ping setiap 10 minit)
- Countdown Timer 30 Saat Berfungsi Sepenuhnya (Live Countdown)
- Panduan Penggunaan Bernombor Lengkap & Mesra Pengguna

Pasang : pip install gradio folium falakpy pandas reportlab qrcode[pil] requests Pillow
Jalan  : python kiblat_search_5days.py
"""

import base64
from datetime import datetime, date
import math
import os
import tempfile
import threading
import time
import traceback
from falakpy import qibla
import folium
import gradio as gr
import pandas as pd
from PIL import Image, ImageDraw
import qrcode
import requests
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    Image as RLImage,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

KAABAH_LAT, KAABAH_LON = 21.422487, 39.826206
FIXED_DAYS = 5
LOGO_FILE = "logo.png"


# ----------------------------------------------------------------------
# 0. Pemantau Percuma (Keep-Alive Self-Ping Setiap 10 Minit)
# ----------------------------------------------------------------------
def start_keep_alive_monitor(interval_seconds=600):
    """Bebenang latar yang memanggil URL pelayan setiap 10 minit untuk mengelakkan mod tidur."""
    def ping_worker():
        time.sleep(25)  # Tunggu pelayan mula beroperasi sepenuhnya
        while True:
            try:
                target_url = os.environ.get("RENDER_EXTERNAL_URL") or "http://127.0.0.1:7860"
                requests.get(target_url, timeout=12)
            except Exception:
                pass
            time.sleep(interval_seconds)

    thread = threading.Thread(target=ping_worker, daemon=True)
    thread.start()


start_keep_alive_monitor()


def get_logo_b64(filepath=LOGO_FILE):
    """Membaca fail logo tempatan dan menukarnya ke format base64."""
    if os.path.exists(filepath):
        try:
            with open(filepath, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        except Exception:
            return ""
    return ""


# ----------------------------------------------------------------------
# 1. Carian Lokasi Geocoding (Nama Tempat -> Lat, Lon)
# ----------------------------------------------------------------------
def search_location(place_name):
    if not place_name or not place_name.strip():
        return None, None, "⚠️ Sila masukkan nama tempat atau alamat."

    url = "https://nominatim.openstreetmap.org/search"
    headers = {"User-Agent": "AplikasiKiblatMalaysia/2.0 (contact@kiblat.local)"}
    params = {"q": place_name.strip(), "format": "json", "limit": 1}

    try:
        res = requests.get(url, params=params, headers=headers, timeout=12)
        res.raise_for_status()
        data = res.json()

        if not data:
            return None, None, "❌ Lokasi tidak dijumpai. Cuba kata kunci lain."

        lat = round(float(data[0]["lat"]), 6)
        lon = round(float(data[0]["lon"]), 6)
        display_name = data[0]["display_name"]
        msg = f"✅ **Lokasi Ditemui:**\n{display_name}\n\n*Koordinat: `{lat}, {lon}`*"
        return lat, lon, msg
    except Exception as e:
        return None, None, f"❌ Ralat carian lokasi: {e}"


# ----------------------------------------------------------------------
# 2. Geodesi Kiblat & Titik Unjuran Peta
# ----------------------------------------------------------------------
def qibla_bearing(lat, lon):
    p1, p2 = math.radians(lat), math.radians(KAABAH_LAT)
    dl = math.radians(KAABAH_LON - lon)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def to_dms(deg):
    d = int(deg)
    m = int((deg - d) * 60)
    s = ((deg - d) * 60 - m) * 60
    return f"{d}° {m}' {s:.1f}\""


def destination_point(lat, lon, bearing_deg, distance_m=2000):
    R = 6378137.0
    b = math.radians(bearing_deg)
    d_div_r = distance_m / R
    lat_rad, lon_rad = math.radians(lat), math.radians(lon)

    end_lat = math.asin(
        math.sin(lat_rad) * math.cos(d_div_r)
        + math.cos(lat_rad) * math.sin(d_div_r) * math.cos(b)
    )
    end_lon = lon_rad + math.atan2(
        math.sin(b) * math.sin(d_div_r) * math.cos(lat_rad),
        math.cos(d_div_r) - math.sin(lat_rad) * math.sin(end_lat),
    )
    return math.degrees(end_lat), math.degrees(end_lon)


def make_folium_map(lat, lon, bearing):
    end_lat, end_lon = destination_point(lat, lon, bearing, 2000)
    d_lat = 50.0 / 111320.0
    d_lon = 50.0 / (111320.0 * math.cos(math.radians(lat)))

    m = folium.Map(
        location=[lat, lon],
        tiles="OpenStreetMap",
        control_scale=True,
        zoom_control=False,
        scrollWheelZoom=False,
        doubleClickZoom=False,
        touchZoom=False,
        dragging=True,
    )
    m.fit_bounds([[lat - d_lat, lon - d_lon], [lat + d_lat, lon + d_lon]])

    folium.CircleMarker(
        [lat, lon],
        radius=6,
        color="#000000",
        fill=True,
        fill_color="#00FFFF",
        fill_opacity=1.0,
        weight=2,
        tooltip="Pusat Lokasi",
    ).add_to(m)

    folium.PolyLine(
        [[lat, lon], [end_lat, end_lon]],
        color="#FF0000",
        weight=4,
        opacity=0.9,
        tooltip=f"Kiblat: {bearing:.2f}°",
    ).add_to(m)

    return m._repr_html_()


# ----------------------------------------------------------------------
# 3. Penjana Dokumen PDF
# ----------------------------------------------------------------------
def save_compass_image(bearing, file_path, size=240):
    img = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    c = size // 2
    r = size // 2 - 18

    draw.ellipse([c - r, c - r, c + r, c + r], outline="#718096", width=2)
    draw.text((c - 5, 2), "U", fill="#E53E3E")
    draw.text((c - 4, size - 16), "S", fill="#4A5568")
    draw.text((size - 14, c - 7), "T", fill="#4A5568")
    draw.text((2, c - 7), "B", fill="#4A5568")

    rad = math.radians(bearing)
    ex = c + (r - 12) * math.sin(rad)
    ey = c - (r - 12) * math.cos(rad)
    draw.line([c, c, ex, ey], fill="#E53E3E", width=4)
    draw.ellipse([c - 4, c - 4, c + 4, c + 4], fill="#1A202C")
    img.save(file_path, format="PNG")


def draw_pdf_canvas_frame(canvas, doc):
    canvas.saveState()
    w, h = A4
    canvas.setStrokeColor(colors.HexColor("#1A365D"))
    canvas.setLineWidth(1.5)
    canvas.rect(20, 20, w - 40, h - 40)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#718096"))
    canvas.drawString(30, 28, "Dokumen Rasmi Dijana Digital - Sah Laku Rujukan Sahaja.")
    canvas.drawRightString(w - 30, 28, f"Halaman {doc.page}")
    canvas.restoreState()


def create_pdf(lat, lon, bearing, df, start_date, place_name, file_path):
    doc = SimpleDocTemplate(
        file_path,
        pagesize=A4,
        rightMargin=36,
        leftMargin=36,
        topMargin=32,
        bottomMargin=36,
    )
    styles = getSampleStyleSheet()
    cell_style = ParagraphStyle(
        "Cell", parent=styles["Normal"], fontSize=7.5, leading=9.5, alignment=1
    )
    cell_meta_style = ParagraphStyle(
        "MetaCell", parent=styles["Normal"], fontSize=8, leading=10, textColor=colors.HexColor("#2D3748")
    )
    elements = []

    # 1. Header Laporan dengan Logo Balai Cerap Negeri Sembilan
    if os.path.exists(LOGO_FILE):
        try:
            logo_img = RLImage(LOGO_FILE, width=54, height=54)
            logo_img.hAlign = "CENTER"
            elements.append(logo_img)
            elements.append(Spacer(1, 4))
        except Exception:
            pass

    elements.append(
        Paragraph(
            "<b>BALAI CERAP NEGERI SEMBILAN</b>",
            ParagraphStyle(
                "InstTitle",
                parent=styles["Normal"],
                fontSize=11,
                leading=14,
                alignment=1,
                textColor=colors.HexColor("#2D5A60"),
                fontName="Helvetica-Bold",
            ),
        )
    )
    elements.append(
        Paragraph(
            "<b>Jadual Arah Kiblat Selari Bayang Matahari (5 HARI)</b>",
            ParagraphStyle(
                "T",
                parent=styles["Heading1"],
                fontSize=13,
                leading=16,
                alignment=1,
                textColor=colors.HexColor("#1A365D"),
            ),
        )
    )
    elements.append(Spacer(1, 8))

    # 2. Gambarajah Kompas Kiblat
    tmp_compass = os.path.join(tempfile.gettempdir(), f"cmp_{os.getpid()}.png")
    save_compass_image(bearing, tmp_compass)
    compass_img = RLImage(tmp_compass, width=95, height=95)
    compass_img.hAlign = "CENTER"
    elements.append(compass_img)
    elements.append(Spacer(1, 10))

    # 3. Parameter Analisis
    lokasi_str = place_name.strip() if place_name and place_name.strip() else f"{lat:.6f}, {lon:.6f}"

    meta_data = [
        [
            "Nama Tempat:",
            Paragraph(lokasi_str, cell_meta_style),
            "Arah Kiblat:",
            f"{bearing:.4f}° ({to_dms(bearing)})",
        ],
        [
            "Koordinat:",
            f"{lat:.6f}, {lon:.6f}",
            "Tarikh Mula:",
            str(start_date),
        ],
        [
            "Kaedah:",
            "Great-Circle & Solar Transit [falakpy]",
            "",
            "",
        ],
    ]
    t_meta = Table(meta_data, colWidths=[85, 175, 85, 175])
    t_meta.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("SPAN", (1, 2), (3, 2)),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    elements.extend([t_meta, Spacer(1, 12)])

    elements.append(
        Paragraph("<b>Jadual Arah Kiblat Selari Matahari (5 Hari)</b>", styles["Heading3"])
    )
    elements.append(Spacer(1, 6))

    # 4. Jadual Analisis Suria
    if not df.empty:
        cols = list(df.columns)
        rows = [
            [
                Paragraph(
                    f"<b>{col}</b>",
                    ParagraphStyle("H", parent=cell_style, textColor=colors.white, fontName="Helvetica-Bold"),
                )
                for col in cols
            ]
        ]
        for _, r in df.iterrows():
            rows.append([Paragraph(str(val), cell_style) for val in r.values])

        col_widths = []
        for c in cols:
            if "Tarikh" in c:
                col_widths.append(70)
            elif "Kedudukan" in c:
                col_widths.append(125)
            elif "Sesi" in c:
                col_widths.append(60)
            elif "Awal" in c:
                col_widths.append(134)
            elif "Akhir" in c:
                col_widths.append(134)
            else:
                col_widths.append((A4[0] - 72) / len(cols))

        t_data = Table(rows, colWidths=col_widths)
        t_data.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2D5A60")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#F8FAFC")],
                    ),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        elements.append(t_data)

    doc.build(
        elements,
        onFirstPage=draw_pdf_canvas_frame,
        onLaterPages=draw_pdf_canvas_frame,
    )

    if os.path.exists(tmp_compass):
        try:
            os.remove(tmp_compass)
        except OSError:
            pass


def upload_pdf(pdf_path):
    url = "https://tmpfiles.org/api/v1/upload"
    headers = {"User-Agent": "Mozilla/5.0"}
    with open(pdf_path, "rb") as f:
        res = requests.post(url, files={"file": f}, headers=headers, timeout=20)
    res.raise_for_status()
    raw_url = res.json()["data"]["url"]
    return raw_url.replace("tmpfiles.org/", "tmpfiles.org/dl/")


def generate_qr(target_url):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(target_url)
    qr.make(fit=True)
    return qr.make_image(fill_color="#1A202C", back_color="white").convert("RGB")


# ----------------------------------------------------------------------
# 4. Aliran Pemprosesan Utama
# ----------------------------------------------------------------------
def process_data(lat, lon, start_date_str, tz, place_name=""):
    if lat is None or lon is None:
        err_msg = "⚠️ Sila cari nama tempat atau masukkan koordinat terlebih dahulu."
        return (
            "<p style='color:red;'>Koordinat tiada.</p>",
            err_msg,
            pd.DataFrame({"Status": ["Sila isi koordinat"]}),
            Image.new("RGB", (200, 200), color=(240, 240, 240)),
            "",
        )

    try:
        bearing = qibla_bearing(lat, lon)
        map_html = make_folium_map(lat, lon, bearing)

        # 1. Analisis Suria Tetap 5 Hari (falakpy)
        dt = datetime.strptime(start_date_str.strip(), "%Y-%m-%d")
        csv_tmp = os.path.join(tempfile.gettempdir(), f"qibla_5d_{os.getpid()}.csv")

        qibla.multiday_qibla(
            lat=lat,
            lon=lon,
            ele=40,
            timezone=float(tz),
            y=dt.year,
            m=dt.month,
            d_start=dt.day,
            num_days=FIXED_DAYS,
            tolerance=2.0,
            csv_filename=csv_tmp,
        )

        df = (
            pd.read_csv(csv_tmp)
            if os.path.exists(csv_tmp)
            else pd.DataFrame({"Status": ["Tiada jajaran ditemui"]})
        )
        if os.path.exists(csv_tmp):
            os.remove(csv_tmp)

        rename_map = {}
        for c in df.columns:
            c_low = c.lower()
            if "date" in c_low:
                rename_map[c] = "Tarikh"
            elif "label" in c_low:
                rename_map[c] = "Kedudukan Bayang"
            elif "entry" in c_low:
                rename_map[c] = "Waktu Awal Bayang Selari Kiblat"
            elif "exit" in c_low:
                rename_map[c] = "Waktu Akhir Bayang Selari Kiblat"

        df = df.rename(columns=rename_map)

        if "Kedudukan Bayang" in df.columns:
            df["Kedudukan Bayang"] = (
                df["Kedudukan Bayang"]
                .astype(str)
                .str.strip()
                .replace({
                    "QIBLA": "Bayang hadap kiblat",
                    "qibla": "Bayang hadap kiblat",
                    "OPPOSITE": "Bayang membelakangi kiblat",
                    "opposite": "Bayang membelakangi kiblat",
                })
            )

        def tentukan_sesi(val):
            if pd.isna(val) or str(val).strip() in ["-", "", "None"]:
                return "-"
            try:
                jam = int(str(val).split(":")[0])
                if jam < 12:
                    return "Pagi"
                elif 12 <= jam < 14:
                    return "Tengah Hari"
                else:
                    return "Petang"
            except Exception:
                return "-"

        if "Waktu Awal Bayang Selari Kiblat" in df.columns:
            df["Sesi"] = df["Waktu Awal Bayang Selari Kiblat"].apply(tentukan_sesi)
            urutan = [
                c
                for c in [
                    "Tarikh",
                    "Kedudukan Bayang",
                    "Sesi",
                    "Waktu Awal Bayang Selari Kiblat",
                    "Waktu Akhir Bayang Selari Kiblat",
                ]
                if c in df.columns
            ]
            df = df[urutan]

        # 2. Bina Dokumen PDF
        pdf_path = os.path.join(
            tempfile.gettempdir(), f"Laporan_Kiblat_{dt.strftime('%Y%m%d')}.pdf"
        )
        create_pdf(lat, lon, bearing, df, start_date_str, place_name, pdf_path)

        # 3. Muat Naik & QR
        direct_pdf_url = upload_pdf(pdf_path)
        qr_img = generate_qr(direct_pdf_url)

        lokasi_info = place_name.strip() if place_name and place_name.strip() else f"`{lat:.6f}, {lon:.6f}`"
        info = f"""
### Keputusan Kiblat
* **Lokasi / Premis:** {lokasi_info}
* **Koordinat:** `{lat:.6f}, {lon:.6f}`
* **Arah Kiblat:** **{bearing:.4f}°** ({to_dms(bearing)}) dari Utara Sebenar
* **Bayang Matahari:** 5 Hari bermula `{start_date_str}`
* **Status:** PDF sedia untuk diimbas.
"""
        qr_status = f"**Pautan Muat Turun:**\n[{direct_pdf_url}]({direct_pdf_url})"
        return map_html, info, df, qr_img, qr_status

    except Exception as e:
        traceback.print_exc()
        err_msg = f"❌ **Ralat:** `{type(e).__name__}: {str(e)}`"
        empty_df = pd.DataFrame({"Ralat": [str(e)]})
        dummy_img = Image.new("RGB", (200, 200), color=(240, 240, 240))
        return "<p style='color:red;'>Ralat pemprosesan.</p>", err_msg, empty_df, dummy_img, err_msg


# ----------------------------------------------------------------------
# 5. Antara Muka Gradio & Gaya CSS
# ----------------------------------------------------------------------
CSS = """
.gradio-container {
    --body-background-fill: #F4F7F6;
    --background-fill-primary: #FFFFFF;
    --background-fill-secondary: #EAF0EE;
    --block-background-fill: #FFFFFF;
    --body-text-color: #1E293B;
    --body-text-color-subdued: #475569;
    --block-title-text-color: #2D5A60;
    --block-label-text-color: #334155;
    --input-background-fill: #FFFFFF;
    --input-border-color: #CBD5E1;
    --border-color-primary: #DCE5E3;
    --block-border-color: #DCE5E3;
    --button-primary-background-fill: #2D5A60;
    --button-primary-background-fill-hover: #23464B;
    --button-primary-text-color: #FFFFFF;
    --button-secondary-background-fill: #FFFFFF;
    --button-secondary-background-fill-hover: #EBF3F2;
    --button-secondary-text-color: #2D5A60;
    --button-secondary-border-color: #2D5A60;
    --block-radius: 14px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    color: #1E293B;
    max-width: 1200px !important;
    margin: 0 auto;
}

.dark .gradio-container {
    --body-background-fill: #0F172A;
    --background-fill-primary: #1E293B;
    --background-fill-secondary: #0F172A;
    --block-background-fill: #1E293B;
    --body-text-color: #E2E8F0;
    --body-text-color-subdued: #94A3B8;
    --block-title-text-color: #5EEAD4;
    --block-label-text-color: #CBD5E1;
    --input-background-fill: #1E293B;
    --input-border-color: #334155;
    --border-color-primary: #334155;
    --block-border-color: #334155;
    color: #E2E8F0;
}

.ns-strip {
    height: 5px;
    background: linear-gradient(90deg, #D4AF37 0%, #E8D48A 50%, #D4AF37 100%);
    border-radius: 6px 6px 0 0;
    margin: 0 4px;
}

.bcns-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
    background: linear-gradient(135deg, #2D5A60 0%, #3B6E75 100%);
    border-radius: 0 0 14px 14px;
    padding: 14px 24px;
    box-shadow: 0 4px 14px rgba(45, 90, 96, 0.15);
    margin-bottom: 14px;
}

.bcns-brand, .bcns-brand * {
    color: #FFFFFF !important;
    font-weight: 700 !important;
    font-size: 1.45rem;
    letter-spacing: -0.01em;
    display: flex;
    align-items: center;
    gap: 14px;
    text-shadow: 0 1px 2px rgba(0, 0, 0, 0.15);
}

.bcns-brand img {
    height: 52px;
    width: 52px;
    filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.2));
}

.bcns-nav {
    color: #F0FDF4 !important;
    font-weight: 600 !important;
    font-size: 0.95rem;
    background: rgba(255, 255, 255, 0.16) !important;
    padding: 6px 14px;
    border-radius: 20px;
    border: 1px solid rgba(255, 255, 255, 0.3) !important;
}

/* Sepanduk Sambungan & Lencana Pemasa */
.connection-banner {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
    background: #FEF3C7;
    border: 1.5px solid #F59E0B;
    border-radius: 12px;
    padding: 12px 18px;
    margin: 0 0 16px 0;
    color: #92400E;
    box-shadow: 0 2px 8px rgba(245, 158, 11, 0.12);
}

.dark .connection-banner {
    background: #1E293B;
    border-color: #F59E0B;
    color: #FDE68A;
}

.connection-banner-text {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 0.92rem;
    line-height: 1.45;
    flex: 1;
}

.connection-timer-badge {
    background: #D97706;
    color: #FFFFFF !important;
    font-weight: 700;
    font-size: 0.92rem;
    padding: 6px 14px;
    border-radius: 20px;
    white-space: nowrap;
    letter-spacing: 0.02em;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.15);
    transition: all 0.3s ease;
}

.hero {
    padding: 6px 4px 14px;
}

.hero h1 {
    color: #2D5A60 !important;
    font-size: 2.1rem;
    line-height: 1.2;
    font-weight: 800;
    margin: 0 0 8px;
}

.dark .hero h1 {
    color: #5EEAD4 !important;
}

.hero h1::after {
    content: "";
    display: block;
    width: 60px;
    height: 4px;
    margin-top: 8px;
    background: #D4AF37;
    border-radius: 2px;
}

.hero p {
    color: #334155 !important;
    font-size: 1.02rem;
    line-height: 1.6;
    margin: 0;
    max-width: 820px;
}

.dark .hero p {
    color: #CBD5E1 !important;
}

.guide-box {
    background: #FFFFFF;
    border: 1.5px solid #DCE5E3;
    border-radius: 14px;
    padding: 16px 20px;
    margin-bottom: 20px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.02);
}

.dark .guide-box {
    background: #1E293B;
    border-color: #334155;
}

.card {
    background: #FFFFFF !important;
    border: 1px solid #DCE5E3 !important;
    border-radius: 14px !important;
    padding: 18px !important;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.02) !important;
}

.dark .card {
    background: #1E293B !important;
    border-color: #334155 !important;
}

.band {
    background: linear-gradient(135deg, #2D5A60 0%, #3B6E75 100%);
    border-radius: 12px;
    padding: 14px 20px;
    text-align: center;
    margin: 20px 0 10px;
}

.band h2 {
    color: #FFFFFF !important;
    font-size: 1.35rem;
    font-weight: 700;
    margin: 0;
    letter-spacing: 0.01em;
}

.gradio-container h3 {
    color: #2D5A60 !important;
    font-weight: 700;
    font-size: 1.08rem;
    border-bottom: 2px solid #E2E8F0;
    padding-bottom: 6px;
    margin-top: 6px;
}

.dark .gradio-container h3 {
    color: #5EEAD4 !important;
    border-bottom-color: #334155;
}

.map-card {
    border-radius: 14px;
    overflow: hidden;
    border: 1px solid #CBD5E1;
}

.gradio-container table thead,
.gradio-container table thead tr,
.gradio-container table thead th,
.gradio-container .table-wrap thead th {
    background-color: #2D5A60 !important;
    background: #2D5A60 !important;
}

.gradio-container table thead th,
.gradio-container table thead th *,
.gradio-container .table-wrap thead th,
.gradio-container .table-wrap thead th * {
    color: #FFFFFF !important;
    font-weight: 700 !important;
}

.dark .gradio-container table thead,
.dark .gradio-container table thead tr,
.dark .gradio-container table thead th,
.dark .gradio-container .table-wrap thead th {
    background-color: #1E3A3E !important;
    background: #1E3A3E !important;
}

.dark .gradio-container table thead th,
.dark .gradio-container table thead th *,
.dark .gradio-container .table-wrap thead th,
.dark .gradio-container .table-wrap thead th * {
    color: #5EEAD4 !important;
}

.gradio-container table tbody td,
.gradio-container .table-wrap tbody td {
    color: #1E293B !important;
}

.dark .gradio-container table tbody td,
.dark .gradio-container .table-wrap tbody td {
    color: #E2E8F0 !important;
    background-color: #1E293B !important;
}
"""


def generate_header_html():
    b64_str = get_logo_b64()
    logo_tag = (
        f"<img src='data:image/png;base64,{b64_str}' alt='Logo Balai Cerap Negeri Sembilan'>"
        if b64_str
        else ""
    )
    return f"""
<style>{CSS}</style>
<div class="ns-strip"></div>
<div class="bcns-header">
  <div class="bcns-brand">
    {logo_tag}
    <span>Balai Cerap Negeri Sembilan</span>
  </div>
  <div class="bcns-nav">Kiblat &amp; Analisis Suria</div>
</div>

<!-- Sepanduk Makluman Sambungan Pangkalan Data & Jam Pemasa 30 Saat -->
<div id="connection-banner-box" class="connection-banner">
  <div class="connection-banner-text">
    <span style="font-size: 1.3rem;">📡</span>
    <span><strong>Makluman Sistem:</strong> Sistem sedang menyambung ke pangkalan data falak. Sila tunggu sebentar jika paparan mengambil masa beberapa saat untuk dimuatkan buat kali pertama.</span>
  </div>
  <div id="connection-timer" class="connection-timer-badge">⏳ 30s</div>
</div>

<div class="hero">
  <h1>Penjana Bayang Matahari Selari Kiblat<br> </h1>
  <p>Apps ini bertujuan untuk anda menentukan arah kiblat di lokasi anda, dan mementukan arah kiblat 
  melaui bayang matahari. </p>
</div>
"""


# JavaScript rasmi Gradio untuk mengira detik (Countdown) 30 saat secara langsung
COUNTDOWN_JS = """
() => {
    let seconds = 30;
    const timerBadge = document.getElementById("connection-timer");
    const banner = document.getElementById("connection-banner-box");
    
    if (!timerBadge) return;
    
    timerBadge.innerText = "⏳ 30s";
    
    const interval = setInterval(() => {
        seconds--;
        if (seconds > 0) {
            timerBadge.innerText = "⏳ " + seconds + "s";
        } else {
            timerBadge.innerText = "✅ Sedia";
            timerBadge.style.background = "#059669";
            clearInterval(interval);
            setTimeout(() => {
                if (banner) {
                    banner.style.transition = "opacity 0.8s ease";
                    banner.style.opacity = "0";
                    setTimeout(() => { banner.style.display = "none"; }, 800);
                }
            }, 2500);
        }
    }, 1000);
}
"""


# ----------------------------------------------------------------------
# 6. Membina Antara Muka Gradio
# ----------------------------------------------------------------------
with gr.Blocks(title="Kiblat & Bayang Matahari 5 Hari - Balai Cerap Negeri Sembilan") as demo:
    gr.HTML(generate_header_html())

    # Panduan Penggunaan Bernombor (Langkah Demi Langkah)
    with gr.Column(elem_classes="guide-box"):
        gr.Markdown(
            """
### 📋 Panduan Penggunaan (5 Langkah Mudah)
1. **Cari Lokasi:** Masukkan nama tempat, masjid, atau alamat premis anda pada ruangan carian, kemudian klik butang **🔍 Cari Lokasi**.
2. **Sahkan Parameter:** Koordinat latitud, longitud, dan tarikh mula akan terisi secara automatik (anda boleh menukar tarikh jika perlu).
3. **Jana Laporan:** Klik butang **Jana Laporan (5 Hari) & QR** untuk memulakan pengiraan algoritma falak.
4. **Semak Unjuran:** Periksa garisan arah kiblat geodesi (2.0 km) pada peta interaktif dan rujuk jadual waktu penjajaran bayang suria harian (Pagi/Tengah Hari/Petang).
5. **Dapatkan PDF & QR:** Imbas **Kod QR** menggunakan kamera telefon pintar anda atau klik pautan yang disediakan untuk memuat turun salinan dokumen rasmi PDF.
"""
        )

    with gr.Row():
        with gr.Column(scale=1, elem_classes="card"):
            gr.Markdown("### 1. Carian Lokasi")
            search_input = gr.Textbox(
                label="Cari Nama Tempat / Alamat Rumah",
                placeholder="Contoh: Masjid Putra Putrajaya / Telok Kemang",
            )
            btn_search = gr.Button("🔍 Cari Lokasi", variant="secondary")
            search_status = gr.Markdown()

            gr.Markdown("### 2. Parameter Analisis")
            lat_in = gr.Number(label="Latitud", value=3.139000, precision=6)
            lon_in = gr.Number(label="Longitud", value=101.686900, precision=6)
            date_in = gr.Textbox(
                label="Tarikh Mula (YYYY-MM-DD)",
                value=date.today().strftime("%Y-%m-%d"),
            )
            tz_in = gr.Number(label="Zon Masa (UTC)", value=8, precision=1)
            btn_run = gr.Button("Jana Laporan (5 Hari) & QR", variant="primary")
            info_out = gr.Markdown()

        with gr.Column(scale=2):
            map_out = gr.HTML(label="Paparan Peta (FOV 100m)", elem_classes="map-card")

    gr.HTML('<div class="band"><h2>Jadual Penjajaran Suria Harian (5 Hari)</h2></div>')
    table_out = gr.Dataframe(interactive=False)

    with gr.Row():
        qr_out = gr.Image(label="Kod QR Laporan PDF (Imbas Guna Telefon)", type="pil", width=240)
        qr_text = gr.Markdown()

    btn_search.click(
        search_location,
        inputs=[search_input],
        outputs=[lat_in, lon_in, search_status],
    )

    btn_run.click(
        process_data,
        inputs=[lat_in, lon_in, date_in, tz_in, search_input],
        outputs=[map_out, info_out, table_out, qr_out, qr_text],
    )

    # Kunci utama: Menjalankan skrip kiraan detik 30s sebaik sahaja aplikasi dimuatkan
    demo.load(fn=None, js=COUNTDOWN_JS)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    demo.launch(server_name="0.0.0.0", server_port=port)
