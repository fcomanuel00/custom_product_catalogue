# -*- coding: utf-8 -*-
# Part of Framarketing. See LICENSE file for full copyright and licensing details.
"""
Modelo permanente `product.catalogue`.

Cada vez que el wizard genera un catálogo, guarda aquí:
  * los filtros y estilo aplicados,
  * los productos incluidos (many2many, para poder reimprimir),
  * el PDF final resultante.

De este modo el usuario puede:
  * consultar el histórico,
  * descargar de nuevo el PDF,
  * reenviar por email sin regenerar.
"""

import base64
import io
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# pypdf es la librería nativa en Odoo 18+. Mantenemos compatibilidad con PyPDF2.
try:
    from pypdf import PdfReader, PdfWriter
except ImportError:  # pragma: no cover
    try:
        from PyPDF2 import PdfReader, PdfWriter
    except ImportError:
        PdfReader = None
        PdfWriter = None


class ProductCatalogue(models.Model):
    _name = 'product.catalogue'
    _description = 'Catálogo de Productos Generado'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    # ── Datos identificativos ────────────────────────────────────────────────
    name = fields.Char(
        string='Nombre',
        required=True,
        tracking=True,
        default=lambda self: _('Catálogo del ') + fields.Date.context_today(self).strftime('%d/%m/%Y'),
    )
    state = fields.Selection(
        [('draft', 'Borrador'), ('done', 'Generado'), ('sent', 'Enviado')],
        default='draft',
        tracking=True,
        string='Estado',
    )
    user_id = fields.Many2one(
        'res.users', string='Creado por',
        default=lambda s: s.env.user, readonly=True,
    )
    date_generated = fields.Datetime(
        string='Fecha generación', default=fields.Datetime.now, readonly=True,
    )

    # ── Productos incluidos ──────────────────────────────────────────────────
    product_ids = fields.Many2many(
        'product.template',
        string='Productos incluidos',
        readonly=True,
    )
    product_count = fields.Integer(
        string='Nº productos', compute='_compute_product_count', store=True,
    )

    # ── Parámetros del catálogo (copiados del wizard, para reimprimir) ──────
    pricelist_id = fields.Many2one(
        'product.pricelist', string='Tarifa', required=True,
    )
    currency_id = fields.Many2one(
        'res.currency', related='pricelist_id.currency_id', readonly=True,
    )

    style = fields.Selection(
        [
            ('1', 'Estilo 1 — Tabla con imagen pequeña'),
            ('2', 'Estilo 2 — Ficha completa por producto'),
            ('3', 'Estilo 3 — Rejilla 3 columnas'),
            ('4', 'Estilo 4 — Cuadrícula con caja grande'),
        ],
        default='1', required=True, string='Estilo',
    )

    image_size = fields.Selection(
        [('small', 'Pequeño'), ('medium', 'Mediano'), ('large', 'Grande')],
        default='medium', string='Tamaño imagen',
    )

    # Campos opcionales a mostrar
    show_price = fields.Boolean(string='Mostrar precio', default=True)
    show_description = fields.Boolean(string='Mostrar descripción', default=True)
    show_reference = fields.Boolean(string='Mostrar referencia interna', default=True)
    show_uom = fields.Boolean(string='Mostrar unidad de medida', default=False)
    show_category = fields.Boolean(string='Mostrar categoría', default=False)

    # Cabecera y pie
    header_html = fields.Html(
        string='Cabecera personalizada',
        sanitize=False,
        help='Texto/HTML que aparece arriba de la primera página del catálogo (tras el PDF de portada si lo hay).',
    )
    footer_html = fields.Html(
        string='Pie personalizado',
        sanitize=False,
        help='Texto/HTML que aparece al final del catálogo (antes del PDF de contraportada si lo hay).',
    )
    header_pdf = fields.Binary(string='PDF de portada', attachment=True)
    header_pdf_filename = fields.Char(string='Nombre PDF portada')
    footer_pdf = fields.Binary(string='PDF de contraportada', attachment=True)
    footer_pdf_filename = fields.Char(string='Nombre PDF contraportada')

    # ── PDF resultante ───────────────────────────────────────────────────────
    pdf_file = fields.Binary(string='Catálogo PDF', attachment=True, readonly=True)
    pdf_filename = fields.Char(string='Nombre archivo', readonly=True)

    # Para el estilo 4 (cuadrícula)
    boxes_per_row = fields.Selection(
        [('2', '2 columnas'), ('3', '3 columnas'), ('4', '4 columnas')],
        default='3', string='Columnas por fila (estilo 4)',
    )

    # ────────────────────────────────────────────────────────────────────────
    #  Computed
    # ────────────────────────────────────────────────────────────────────────
    @api.depends('product_ids')
    def _compute_product_count(self):
        for rec in self:
            rec.product_count = len(rec.product_ids)

    # ────────────────────────────────────────────────────────────────────────
    #  Helpers
    # ────────────────────────────────────────────────────────────────────────
    def _get_image_size_px(self):
        """Píxeles de alto a aplicar a la imagen del producto según la opción."""
        return {'small': 60, 'medium': 100, 'large': 160}.get(self.image_size, 100)

    def get_product_price(self, product):
        """
        Devuelve el precio del producto en la tarifa seleccionada.
        Usamos _get_product_price que ya existe en Odoo y maneja reglas complejas.
        """
        self.ensure_one()
        if not self.pricelist_id:
            return product.list_price
        # Odoo 17+: método público del pricelist
        return self.pricelist_id._get_product_price(
            product=product.product_variant_id or product,
            quantity=1.0,
        )

    def _get_sorted_products(self):
        """Productos ordenados por categoría + nombre para que el PDF salga coherente."""
        self.ensure_one()
        return self.product_ids.sorted(key=lambda p: (p.categ_id.complete_name or '', p.name or ''))

    # ────────────────────────────────────────────────────────────────────────
    #  Helpers de VARIANTES (product.product vs product.template)
    # ────────────────────────────────────────────────────────────────────────
    def _has_real_variants(self, product):
        """
        Un product.template "tiene variantes reales" cuando tiene más de una
        product.product asociada. Los productos sin combinaciones de
        atributos siempre tienen 1 product.product automática.
        """
        return product.product_variant_count > 1

    def _get_variants(self, product):
        """
        Devuelve las product.product (variantes) asociadas al template
        ordenadas por nombre. Solo tiene sentido llamarlo si _has_real_variants.
        """
        return product.product_variant_ids.sorted(key=lambda v: v.display_name)

    def _get_variant_attrs_text(self, variant):
        """
        Devuelve los atributos de una variante como texto legible:
        'Color: Azul, Talla: 75'

        En Odoo, cada variante tiene `product_template_attribute_value_ids`,
        que son los valores de atributo concretos (con su etiqueta "Color:Azul").
        """
        parts = []
        for ptav in variant.product_template_attribute_value_ids:
            parts.append('%s: %s' % (ptav.attribute_id.name, ptav.name))
        return ', '.join(parts)

    def get_variant_price(self, variant):
        """
        Precio de una variante concreta (product.product) en la tarifa seleccionada.
        A diferencia de get_product_price, aquí le pasamos directamente la variante.
        """
        self.ensure_one()
        if not self.pricelist_id:
            return variant.lst_price
        return self.pricelist_id._get_product_price(
            product=variant,
            quantity=1.0,
        )

    # ────────────────────────────────────────────────────────────────────────
    #  Generación del PDF
    # ────────────────────────────────────────────────────────────────────────
    def action_generate_pdf(self):
        """
        Renderiza la plantilla QWeb para este catálogo y, si hay PDFs de
        portada/contraportada, los fusiona. Guarda el resultado en `pdf_file`.
        """
        self.ensure_one()
        if not self.product_ids:
            raise UserError(_('No hay productos en el catálogo. Añade productos antes de generar el PDF.'))

        report_ref = 'custom_product_catalogue.action_report_product_catalogue'
        report = self.env.ref(report_ref)
        # _render_qweb_pdf devuelve (bytes_pdf, 'pdf')
        pdf_content, _ext = report._render_qweb_pdf(report_ref, res_ids=[self.id])

        # Si hay PDFs de portada/contraportada, los fusionamos
        if (self.header_pdf or self.footer_pdf) and PdfReader is not None:
            pdf_content = self._merge_cover_pdfs(pdf_content)
        elif (self.header_pdf or self.footer_pdf) and PdfReader is None:
            _logger.warning(
                'pypdf/PyPDF2 no disponible; se ignoran portada/contraportada. '
                'Instala con: pip install pypdf --break-system-packages'
            )

        self.write({
            'pdf_file': base64.b64encode(pdf_content),
            'pdf_filename': '%s.pdf' % (self.name or 'catalogo'),
            'state': 'done',
        })
        return True

    def _merge_cover_pdfs(self, main_pdf_bytes):
        """Antepone header_pdf y pospone footer_pdf al PDF principal."""
        self.ensure_one()
        writer = PdfWriter()

        def _append_pdf(b64_data):
            if not b64_data:
                return
            try:
                reader = PdfReader(io.BytesIO(base64.b64decode(b64_data)))
                for page in reader.pages:
                    writer.add_page(page)
            except Exception as e:
                _logger.exception('No se pudo leer PDF adjunto: %s', e)

        _append_pdf(self.header_pdf)
        # PDF principal
        reader_main = PdfReader(io.BytesIO(main_pdf_bytes))
        for page in reader_main.pages:
            writer.add_page(page)
        _append_pdf(self.footer_pdf)

        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()

    # ────────────────────────────────────────────────────────────────────────
    #  Acciones de interfaz
    # ────────────────────────────────────────────────────────────────────────
    def action_print_pdf(self):
        """Devuelve la acción estándar para imprimir el informe del catálogo."""
        self.ensure_one()
        return self.env.ref('custom_product_catalogue.action_report_product_catalogue').report_action(self)

    def action_download_stored_pdf(self):
        """Devuelve la URL de descarga del PDF ya almacenado en el registro."""
        self.ensure_one()
        if not self.pdf_file:
            raise UserError(_('Aún no se ha generado el PDF. Pulsa "Generar PDF" primero.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/product.catalogue/%s/pdf_file/%s?download=true' % (
                self.id, self.pdf_filename or 'catalogo.pdf'
            ),
            'target': 'self',
        }

    def action_send_email(self):
        """
        Abre el compositor de email con la plantilla de catálogo precargada
        y el PDF del catálogo ya adjuntado.

        Por qué manejamos el adjunto aquí en lugar de declararlo en la
        mail.template XML: en Odoo 19 los campos `report_template` /
        `report_template_ids` / `report_name` de mail.template fueron
        retirados o renombrados. Generar el attachment en Python es
        compatible con todas las versiones recientes.
        """
        self.ensure_one()
        if not self.pdf_file:
            self.action_generate_pdf()

        template = self.env.ref(
            'custom_product_catalogue.mail_template_product_catalogue',
            raise_if_not_found=False,
        )

        # Creamos el ir.attachment con el PDF ya generado del catálogo.
        # res_model/res_id apuntan al propio registro para que quede ligado.
        attachment = self.env['ir.attachment'].create({
            'name': self.pdf_filename or ('%s.pdf' % (self.name or 'catalogo')),
            'type': 'binary',
            'datas': self.pdf_file,
            'res_model': 'product.catalogue',
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })

        ctx = {
            'default_model': 'product.catalogue',
            'default_res_ids': [self.id],
            'default_use_template': bool(template),
            'default_template_id': template.id if template else False,
            'default_composition_mode': 'comment',
            'default_attachment_ids': [(6, 0, [attachment.id])],
            'mark_so_as_sent': True,
        }
        return {
            'name': _('Enviar Catálogo por Email'),
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'mail.compose.message',
            'target': 'new',
            'context': ctx,
        }
