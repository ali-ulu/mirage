"""
MIRAGE — Task 02: Pasif Honeytoken Enjeksiyon Modülü.

Yasal çerçeve:
  - Kurban makinede HİÇBİR kod çalıştırmaz.
  - Excel dosyası açıldığında yalnızca zararsız HTTP GET isteği tetiklenir.
  - PowerShell, DDE, makro, VBA, DNS tunneling KESİNLİKLE YOK.

Teknik yaklaşım:
  1. openpyxl ile DataFrame'i normal bir XLSX'e yaz.
  2. XLSX (aslında ZIP) içeriğini zipfile ile aç.
  3. xl/drawings/drawing1.xml oluştur: 1x1 pixel-anchor'lı çizim tanımı.
  4. xl/drawings/_rels/drawing1.xml.rels oluştur: External relationship
     to tracking URL (TargetMode="External").
  5. xl/worksheets/_rels/sheet1.xml.rels (yoksa oluştur): drawing1 referansı.
  6. xl/worksheets/sheet1.xml'e <drawing> elementi ekle.
  7. [Content_Types].xml'e Drawing override ekle.
  8. Tüm dosyaları yeniden ZIP'le.

Excel dosyası açıldığında, relationship'i resolve etmek için tracking URL'e
HTTP GET isteği gönderir. Sunucu bu isteği alır → IP, User-Agent, timestamp
kaydeder → Task 03'ün webhook'una düşer.
"""
from __future__ import annotations

import io
import json
import os
import re
import uuid
import zipfile
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
from openpyxl import Workbook


# =============================================================================
# Yasaklı pattern'ler — bu liste herhangi bir üretim çıktısında ASLA bulunamaz
# =============================================================================
MIRAGE_FORBIDDEN_PATTERNS: tuple[str, ...] = (
    "powershell",
    "cmd|",
    "wscript",
    "cscript",
    "mshta",
    "vbaProject",
    "Auto_Open",
    "Workbook_Open",
    "Sub ",
    "End Sub",
    "nslookup",
    "iodine",
    "dnscat",
    "dns_tunnel",
    "javascript:",
    "file://",
    "smb://",
    "ftp://",
)


# =============================================================================
# Registry — Task 03 ile köprü
# =============================================================================
@dataclass
class HoneytokenRecord:
    """Tek bir honeytoken üretiminin kaydı."""
    token: str
    base_url: str
    full_url: str
    label: str
    row_count: int
    columns: list[str]
    created_at: str  # ISO8601
    file_sha256: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "HoneytokenRecord":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


class HoneytokenRegistry:
    """
    Honeytoken kayıt defteri. Token -> HoneytokenRecord eşlemesini tutar.

    Persistence: opsiyonel JSON dosyasına save/load.
    Task 03 (beacon receiver) bu registry'yi kullanarak gelen HTTP
    isteklerini, üretim zamanındaki dosya ile eşleştirir.
    """

    def __init__(self, path: Optional[str | Path] = None):
        self.path = Path(path) if path else None
        self._records: dict[str, HoneytokenRecord] = {}

    def issue(
        self,
        df: pd.DataFrame,
        base_url: str,
        label: str = "",
    ) -> HoneytokenRecord:
        """Yeni bir honeytoken üret, kaydet ve record döndür."""
        token = str(uuid.uuid4())
        full_url = f"{base_url.rstrip('/')}/{token}"
        record = HoneytokenRecord(
            token=token,
            base_url=base_url,
            full_url=full_url,
            label=label,
            row_count=len(df),
            columns=list(df.columns),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._records[token] = record
        return record

    def lookup(self, token: str) -> Optional[HoneytokenRecord]:
        return self._records.get(token)

    def all_records(self) -> list[HoneytokenRecord]:
        return list(self._records.values())

    def save(self) -> None:
        if self.path is None:
            raise RuntimeError("Registry path not set — cannot save")
        data = {
            "version": 1,
            "records": [r.to_dict() for r in self._records.values()],
        }
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        data = json.loads(self.path.read_text())
        self._records = {
            r["token"]: HoneytokenRecord.from_dict(r)
            for r in data.get("records", [])
        }


# =============================================================================
# XLSX manipülasyon yardımcıları
# =============================================================================
def _build_drawing_xml() -> str:
    """
    xl/drawings/drawing1.xml içeriği.
    1x1 (EMÜ) boyutunda, A1 hücresine anchor'lı görünmez bir çizim tanımlar.

    ÖNEMLİ: r:embed (internal image) yerine r:link (external image) kullanırız.
      - r:embed → openpyxl image'i ZIP'ten okumaya çalışır, external URL olunca patlar
      - r:link  → openpyxl image'i yüklemeye çalışmaz, Excel ise URL'i resolve etmek için
                  HTTP GET atar (dosya açıldığında otomatik)
    """
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<xdr:wsDr '
        'xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">\n'
        '  <xdr:twoCellAnchor editAs="oneCell">\n'
        '    <xdr:from>\n'
        '      <xdr:col>0</xdr:col><xdr:colOff>0</xdr:colOff>\n'
        '      <xdr:row>0</xdr:row><xdr:rowOff>0</xdr:rowOff>\n'
        '    </xdr:from>\n'
        '    <xdr:to>\n'
        '      <xdr:col>1</xdr:col><xdr:colOff>0</xdr:colOff>\n'
        '      <xdr:row>1</xdr:row><xdr:rowOff>0</xdr:rowOff>\n'
        '    </xdr:to>\n'
        '    <xdr:pic>\n'
        '      <xdr:nvPicPr>\n'
        '        <xdr:cNvPr id="1" name="MIRAGE Token 1"/>\n'
        '        <xdr:cNvPicPr><a:picLocks noChangeAspect="1"/></xdr:cNvPicPr>\n'
        '      </xdr:nvPicPr>\n'
        '      <xdr:blipFill>\n'
        '        <a:blip r:link="rId1" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/>\n'
        '        <a:stretch><a:fillRect/></a:stretch>\n'
        '      </xdr:blipFill>\n'
        '      <xdr:spPr>\n'
        '        <a:xfrm><a:off x="0" y="0"/><a:ext cx="1" cy="1"/></a:xfrm>\n'
        '        <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>\n'
        '      </xdr:spPr>\n'
        '    </xdr:pic>\n'
        '    <xdr:clientData/>\n'
        '  </xdr:twoCellAnchor>\n'
        '</xdr:wsDr>\n'
    )


def _build_drawing_rels_xml(tracking_url: str) -> str:
    """
    xl/drawings/_rels/drawing1.xml.rels içeriği.
    rId1 relationship'i → tracking URL (TargetMode=External).
    Excel bu URL'i resolve etmek için HTTP GET atar.
    """
    # XML attribute escaping
    safe_url = (
        tracking_url
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships '
        'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        f'  <Relationship Id="rId1" '
        f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
        f'Target="{safe_url}" '
        f'TargetMode="External"/>\n'
        '</Relationships>\n'
    )


def _build_worksheet_rels_xml(drawing_rid: str = "rId1") -> str:
    """
    xl/worksheets/_rels/sheet1.xml.rels içeriği.
    Sheet → drawing1 relationship (TargetMode External DEĞİL — dahili).
    """
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships '
        'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        f'  <Relationship Id="{drawing_rid}" '
        f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" '
        f'Target="../drawings/drawing1.xml"/>\n'
        '</Relationships>\n'
    )


def _inject_drawing_ref_into_sheet(sheet_xml: str) -> str:
    """
    xl/worksheets/sheet1.xml içine <drawing r:id="rId1"/> elementi ekle.
    </worksheet> kapanış tag'inin hemen öncesine yerleştirir.
    """
    drawing_tag = '<drawing r:id="rId1" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/>'
    if drawing_tag in sheet_xml:
        return sheet_xml  # already present
    # </worksheet> tag'inden hemen önce ekle
    pattern = re.compile(r"(</worksheet>\s*$)", re.MULTILINE)
    if not pattern.search(sheet_xml):
        raise ValueError("sheet1.xml </worksheet> kapanışı bulunamadı")
    return pattern.sub(f"{drawing_tag}\n\\1", sheet_xml)


def _add_drawing_override_to_content_types(content_types_xml: str) -> str:
    """
    [Content_Types].xml içine drawing override ekle.
    <Types> kapanışından hemen önce.
    """
    override = (
        '<Override PartName="/xl/drawings/drawing1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.drawingml.spreadsheetDrawing+xml"/>'
    )
    if override in content_types_xml:
        return content_types_xml
    pattern = re.compile(r"(</Types>\s*$)", re.MULTILINE)
    if not pattern.search(content_types_xml):
        raise ValueError("[Content_Types].xml </Types> kapanışı bulunamadı")
    return pattern.sub(f"{override}\n\\1", content_types_xml)


# =============================================================================
# Ana inject_honeytoken fonksiyonu
# =============================================================================
def inject_honeytoken(
    df: pd.DataFrame,
    base_url: str,
    sheet_name: str = "Sheet",
    token: Optional[str] = None,
) -> bytes:
    """
    DataFrame'i XLSX'e çevir, içine pasif tracking URL'i göm, bytes döndür.

    Args:
        df: Yazılacak veri
        base_url: Tracking URL'in base kısmı (örn. "https://beacon.mirage.local/track")
        sheet_name: Sheet adı (default "Sheet")
        token: Önceden belirlenmiş token (None ise rastgele UUID üretilir)

    Returns:
        XLSX dosyasının bytes hali.

    Güvenlik:
        - Hiçbir macro/VBA/DDE/PowerShell içermez.
        - Dosya açıldığında yalnızca HTTP GET tetiklenir.
    """
    if token is None:
        token = str(uuid.uuid4())
    tracking_url = f"{base_url.rstrip('/')}/{token}"

    # 1. DataFrame'i openpyxl ile normal XLSX'e yaz
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    # Header
    ws.append(list(df.columns))
    # Body
    for _, row in df.iterrows():
        ws.append([_normalize_cell(v) for v in row.tolist()])
    buf = io.BytesIO()
    wb.save(buf)
    base_xlsx = buf.getvalue()

    # 2. ZIP'i aç, dosyaları oku
    input_zip = zipfile.ZipFile(io.BytesIO(base_xlsx), "r")
    # Tüm üyeleri bir dict'e oku
    members: dict[str, bytes] = {}
    for name in input_zip.namelist():
        members[name] = input_zip.read(name)
    input_zip.close()

    # 3. Hangi sheet dosyasını modifiye edeceğimizi bul
    # openpyxl genelde "xl/worksheets/sheet1.xml" kullanır
    sheet_path = f"xl/worksheets/sheet1.xml"
    if sheet_path not in members:
        # fallback: ilk sheet dosyasını bul
        sheet_candidates = [
            n for n in members
            if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")
        ]
        if not sheet_candidates:
            raise RuntimeError("XLSX içinde sheet1.xml bulunamadı")
        sheet_path = sheet_candidates[0]

    # 4. sheet1.xml'e <drawing> referansı ekle
    sheet_xml = members[sheet_path].decode("utf-8")
    sheet_xml = _inject_drawing_ref_into_sheet(sheet_xml)
    members[sheet_path] = sheet_xml.encode("utf-8")

    # 5. sheet1.xml.rels oluştur veya güncelle
    sheet_rels_path = f"xl/worksheets/_rels/{Path(sheet_path).name}.rels"
    if sheet_rels_path in members:
        # Mevcut rels dosyasına drawing relationship ekle
        existing = members[sheet_rels_path].decode("utf-8")
        # Mevcut rId'leri bul, yeni rId üret
        existing_rids = re.findall(r'Id="(rId\d+)"', existing)
        max_rid = max(
            (int(re.search(r"\d+", rid).group()) for rid in existing_rids),
            default=0,
        )
        new_rid = f"rId{max_rid + 1}"
        new_rel = (
            f'  <Relationship Id="{new_rid}" '
            f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" '
            f'Target="../drawings/drawing1.xml"/>\n'
        )
        # </Relationships> kapanışından önce ekle
        updated = re.sub(
            r"(</Relationships>\s*$)",
            new_rel + r"\1",
            existing,
            flags=re.MULTILINE,
        )
        # sheet_xml'deki r:id referansını güncelle
        sheet_xml = sheet_xml.replace('r:id="rId1"', f'r:id="{new_rid}"')
        members[sheet_path] = sheet_xml.encode("utf-8")
        members[sheet_rels_path] = updated.encode("utf-8")
    else:
        # Yeni rels dosyası oluştur
        members[sheet_rels_path] = _build_worksheet_rels_xml("rId1").encode("utf-8")

    # 6. drawing1.xml ve rels dosyalarını ekle
    members["xl/drawings/drawing1.xml"] = _build_drawing_xml().encode("utf-8")
    members["xl/drawings/_rels/drawing1.xml.rels"] = (
        _build_drawing_rels_xml(tracking_url).encode("utf-8")
    )

    # 7. [Content_Types].xml'e drawing override ekle
    ct_path = "[Content_Types].xml"
    ct_xml = members[ct_path].decode("utf-8")
    ct_xml = _add_drawing_override_to_content_types(ct_xml)
    members[ct_path] = ct_xml.encode("utf-8")

    # 8. Yasaklı pattern kontrolü (defensive)
    for name, content in members.items():
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            continue
        text_lower = text.lower()
        for pattern in MIRAGE_FORBIDDEN_PATTERNS:
            if pattern.lower() in text_lower:
                raise RuntimeError(
                    f"GÜVENLİK İHLALİ: yasaklı pattern '{pattern}' "
                    f"{name} içinde bulundu. Üretim iptal edildi."
                )

    # 9. Yeni ZIP oluştur
    out_buf = io.BytesIO()
    with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return out_buf.getvalue()


def _normalize_cell(value) -> object:
    """pandas/numpy değerlerini openpyxl'in kabul edeceği tipe normalize et."""
    import numpy as np
    if value is None:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.to_pydatetime()
    if isinstance(value, float) and pd.isna(value):
        return None
    return value


# =============================================================================
# Registry + inject birlikte kullanım için convenience fonksiyon
# =============================================================================
def inject_honeytoken_with_record(
    df: pd.DataFrame,
    base_url: str,
    registry: HoneytokenRegistry,
    label: str = "",
    sheet_name: str = "Sheet",
) -> tuple[bytes, HoneytokenRecord]:
    """
    inject_honeytoken + HoneytokenRegistry birlikte.
    Token registry'ye kaydedilir, böylece Task 03 beacon geldiğinde eşleştirilebilir.
    """
    record = registry.issue(df, base_url=base_url, label=label)
    xlsx_bytes = inject_honeytoken(
        df, base_url=base_url, sheet_name=sheet_name, token=record.token
    )
    return xlsx_bytes, record
