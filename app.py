from flask import Flask, send_file, jsonify
import requests
import os
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import LETTER
from io import BytesIO
import textwrap

app = Flask(__name__)

# ------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------
BASE_URL = "https://sgr-infosec.my.onetrust.com/api/controls/v1/control-implementations/pages"
ONETRUST_TOKEN = os.getenv("ONETRUST_TOKEN")

HEADERS = {
    "accept": "application/json",
    "content-type": "application/json",
    "authorization": f"Bearer {ONETRUST_TOKEN}"
}

# ------------------------------------------------------------
# HEALTH CHECK
# ------------------------------------------------------------
@app.route("/")
def health():
    return jsonify({"status": "ok", "message": "OneTrust report service running"})

# ------------------------------------------------------------
# FETCH CONTROLS (WITH PAGINATION)
# ------------------------------------------------------------
def fetch_controls(org_id):
    controls = []
    page = 0
    size = 50

    while True:
        payload = {
            "filters": [
                {
                    "field": "organizationId",
                    "operator": "EQUAL_TO",
                    "value": org_id
                }
            ]
        }

        paged_url = f"{BASE_URL}?page={page}&size={size}"
        response = requests.post(
            paged_url,
            headers=HEADERS,
            json=payload,
            verify=False,
            timeout=60
        )
        response.raise_for_status()

        data = response.json()
        controls.extend(data.get("content", []))

        total_pages = data.get("totalPages", 1)
        page += 1
        if page >= total_pages:
            break

    return controls

# ------------------------------------------------------------
# SORT IDENTIFIERS NUMERICALLY
# ------------------------------------------------------------
def identifier_key(item):
    identifier = (item.get("control") or {}).get("identifier", "")
    parts = []
    for part in identifier.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return parts

# ------------------------------------------------------------
# PDF GENERATION
# ------------------------------------------------------------
def generate_pdf(controls):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=LETTER)

    width, height = LETTER
    x_margin = 40
    y_margin = 40
    y = height - y_margin
    line_height = 14

    def draw_wrapped(text):
        nonlocal y
        for line in textwrap.wrap(text, 100):
            if y <= y_margin:
                c.showPage()
                c.setFont("Helvetica", 10)
                y = height - y_margin
            c.drawString(x_margin, y, line)
            y -= line_height

    controls.sort(key=identifier_key)

    company_name = "Unknown Company"
    for item in controls:
        control = item.get("control") or {}
        if control.get("orgGroupName"):
            company_name = control["orgGroupName"]
            break
        primary = item.get("primaryEntity") or {}
        if primary.get("name"):
            company_name = primary["name"]
            break

    values = []
    for item in controls:
        attrs = item.get("attributes") or {}
        formula = attrs.get("AttributeFormulaValue.value1_2") or []
        val = formula[0].get("value") if formula else None
        if val not in (None, "0", 0):
            try:
                values.append(float(val))
            except ValueError:
                pass

    avg = sum(values) / len(values) if values else None

    c.setFont("Helvetica-Bold", 14)
    c.drawString(x_margin, y, f"OneTrust Controls Summary - {company_name}")
    y -= 20

    c.setFont("Helvetica-Bold", 12)
    avg_text = (
        f"Average Score of Applicable Controls: {avg:.2f}"
        if avg is not None
        else "Average Score of Applicable Controls: N/A"
    )
    c.drawString(x_margin, y, avg_text)
    y -= 30

    c.setFont("Helvetica", 10)

    for item in controls:
        control = item.get("control") or {}
        identifier = control.get("identifier", "N/A")
        name = control.get("name", "N/A")
        description = control.get("description", "N/A")

        attrs = item.get("attributes") or {}
        formula = attrs.get("AttributeFormulaValue.value1_2") or []
        raw_value = formula[0].get("value") if formula else None
        value = raw_value if raw_value not in (None, "0", 0) else "N/A"

        effectiveness = (item.get("effectivenessInfo") or {}).get("name", "N/A")

        draw_wrapped(f"Identifier    : {identifier}")
        draw_wrapped(f"Name          : {name}")
        draw_wrapped(f"Description   : {description}")
        draw_wrapped(f"Value         : {value}")
        draw_wrapped(f"Effectiveness : {effectiveness}")
        draw_wrapped("-" * 90)

    c.save()
    buffer.seek(0)
    return buffer

# ------------------------------------------------------------
# DOWNLOAD ENDPOINT
# ------------------------------------------------------------
@app.route("/report/<org_id>")
def download_report(org_id):
    controls = fetch_controls(org_id)
    pdf = generate_pdf(controls)
    return send_file(
        pdf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"controls_{org_id}.pdf"
    )

# ------------------------------------------------------------
# FLASK APP ENTRYPOINT FOR AZURE
# ------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))  # Azure sets PORT dynamically
    app.run(host="0.0.0.0", port=port)
