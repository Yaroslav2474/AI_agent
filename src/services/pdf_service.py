import os
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import logging

logger = logging.getLogger(__name__)

class PDFService:
    def __init__(self):
        self.font_path = self._get_font_path()
        self._register_font()

    def _get_font_path(self):
        """Get path to Cyrillic font"""
        # Try to find DejaVuSans font in common locations
        possible_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/TTF/DejaVuSans.ttf",
            "C:/Windows/Fonts/arial.ttf",  # Fallback for Windows
            "/System/Library/Fonts/Helvetica.ttc",  # macOS fallback
        ]

        for path in possible_paths:
            if os.path.exists(path):
                return path

        # If no font found, use default (will not support Cyrillic properly)
        logger.warning("No Cyrillic font found, PDF may not display Russian text correctly")
        return None

    def _register_font(self):
        """Register TrueType font with Cyrillic support"""
        if self.font_path and os.path.exists(self.font_path):
            try:
                pdfmetrics.registerFont(TTFont('Cyrillic', self.font_path))
                logger.info(f"Registered Cyrillic font from {self.font_path}")
            except Exception as e:
                logger.exception(f"Failed to register font: {e}")
        else:
            logger.warning("Using default font - Cyrillic text may not display correctly")

    def generate_guest_card(self, booking_id, booking_data, costs, kpp_string, output_dir="src/static/pdfs"):
        """Generate PDF guest registration card"""
        os.makedirs(output_dir, exist_ok=True)

        filename = f"{booking_id}_card.pdf"
        filepath = os.path.join(output_dir, filename)

        doc = SimpleDocTemplate(
            filepath,
            pagesize=A4,
            rightMargin=2*cm,
            leftMargin=2*cm,
            topMargin=2*cm,
            bottomMargin=2*cm
        )

        styles = getSampleStyleSheet()

        # Custom styles
        if self.font_path:
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontName='Cyrillic',
                fontSize=18,
                textColor=colors.darkblue,
                alignment=1,  # center
                spaceAfter=20
            )
            normal_style = ParagraphStyle(
                'CustomNormal',
                parent=styles['Normal'],
                fontName='Cyrillic',
                fontSize=11,
                spaceAfter=10
            )
            header_style = ParagraphStyle(
                'CustomHeader',
                parent=styles['Heading2'],
                fontName='Cyrillic',
                fontSize=14,
                textColor=colors.darkblue,
                spaceAfter=10
            )
        else:
            title_style = styles['Heading1']
            normal_style = styles['Normal']
            header_style = styles['Heading2']

        # Build content
        content = []

        # Title
        content.append(Paragraph("КАРТОЧКА РЕГИСТРАЦИИ ГОСТЯ", title_style))
        content.append(Paragraph("(Турбаза Речка и Песок)", normal_style))
        content.append(Spacer(1, 0.5*cm))

        # Booking information table
        table_data = [
            ["Параметр", "Значение"],
            ["Номер брони", booking_data.get("booking_id", "")],
            ["ФИО гостя", booking_data.get("guest_name", "")],
            ["Домик", booking_data.get("house_id", "")],
            ["Дата заезда", booking_data.get("arrival_date", "")],
            ["Дата выезда", booking_data.get("departure_date", "")],
            ["Время прибытия", booking_data.get("arrival_time", "")],
            ["Количество гостей", f"{booking_data.get('adults', 0)} взрослых, {booking_data.get('children', 0)} детей"],
            ["Автомобиль", "Да" if booking_data.get("has_car") else "Нет"],
        ]

        if booking_data.get("has_car") and booking_data.get("car_plates"):
            table_data.append(["Госномер", ", ".join(booking_data["car_plates"])])

        if kpp_string:
            table_data.append(["Пропуск КПП", kpp_string])

        table_data.append(["Питомец", "Да" if booking_data.get("has_pet") else "Нет"])

        # Create table
        table = Table(table_data, colWidths=[5*cm, 8*cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (1, 0), colors.lightgrey),
            ('TEXTCOLOR', (0, 0), (1, 0), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Cyrillic' if self.font_path else 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))

        content.append(table)
        content.append(Spacer(1, 1*cm))

        # Additional services
        if costs:
            content.append(Paragraph("Дополнительные услуги:", header_style))
            services_data = [["Услуга", "Стоимость"]]
            for key, cost in costs.items():
                item_name = cost.get("item", key)
                total = cost.get("total", "по запросу")
                services_data.append([item_name, f"{total} руб." if isinstance(total, (int, float)) else total])

            services_table = Table(services_data, colWidths=[5*cm, 8*cm])
            services_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (1, 0), colors.lightgrey),
                ('TEXTCOLOR', (0, 0), (1, 0), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, -1), 'Cyrillic' if self.font_path else 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ]))
            content.append(services_table)
            content.append(Spacer(1, 1*cm))

        # Passport data section (empty for manual filling)
        content.append(Paragraph("ПАСПОРТНЫЕ ДАННЫЕ (заполняется при заселении):", header_style))
        passport_data = [
            ["Серия/Номер:", "_____________________"],
            ["Выдан:", "________________________________________________"],
            ["Дата выдачи:", "_____________________"],
        ]

        passport_table = Table(passport_data, colWidths=[4*cm, 9*cm])
        passport_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Cyrillic' if self.font_path else 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('LINEABOVE', (1, 0), (1, -1), 1, colors.black),
        ]))
        content.append(passport_table)
        content.append(Spacer(1, 1.5*cm))

        # Signatures
        signature_data = [
            ["Подпись гостя:", "_____________________"],
            ["", ""],
            ["Подпись администратора:", "_____________________"],
        ]

        signature_table = Table(signature_data, colWidths=[5*cm, 8*cm])
        signature_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Cyrillic' if self.font_path else 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('LINEABOVE', (1, 0), (1, 0), 1, colors.black),
            ('LINEABOVE', (1, 2), (1, 2), 1, colors.black),
        ]))
        content.append(signature_table)

        # Date
        content.append(Spacer(1, 1*cm))
        content.append(Paragraph(f"Дата заполнения: {datetime.now().strftime('%d.%m.%Y')}", normal_style))

        # Build PDF
        try:
            doc.build(content)
            logger.info(f"PDF generated successfully: {filepath}")
            return filepath
        except Exception as e:
            logger.exception(f"Failed to generate PDF: {e}")
            return None

# Global instance
pdf_service = PDFService()
