# -*- coding: utf-8 -*-
# Part of Framarketing. See LICENSE file for full copyright and licensing details.
"""
Wizard para generar un catálogo de productos.

Flujo:
  1. El usuario elige filtros (productos, categorías, solo publicados web),
     tarifa, estilo, tamaño de imagen, campos a mostrar, cabecera y pie.
  2. Al pulsar "Generar", calculamos la lista de productos resultante,
     creamos un registro permanente en `product.catalogue` y llamamos a
     su método `action_generate_pdf` para que renderice y guarde el PDF.
  3. Abrimos el registro creado en modo formulario para que el usuario
     pueda descargar, reenviar o volver a imprimir.
"""

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ProductCatalogueWizard(models.TransientModel):
    _name = 'product.catalogue.wizard'
    _description = 'Asistente generador de catálogos'

    # ── Identificación ──────────────────────────────────────────────────────
    name = fields.Char(
        string='Nombre del catálogo',
        required=True,
        default=lambda self: _('Catálogo del ') + fields.Date.context_today(self).strftime('%d/%m/%Y'),
    )

    # ── Filtros de productos ────────────────────────────────────────────────
    filter_mode = fields.Selection(
        [
            ('all', 'Todos los productos'),
            ('by_products', 'Productos concretos'),
            ('by_categories', 'Por categorías'),
        ],
        default='all', required=True, string='Filtrar por',
    )
    product_ids = fields.Many2many(
        'product.template',
        'cat_wiz_prod_rel', 'wiz_id', 'prod_id',
        string='Productos',
    )
    category_ids = fields.Many2many(
        'product.category',
        'cat_wiz_categ_rel', 'wiz_id', 'categ_id',
        string='Categorías',
    )
    only_website_published = fields.Boolean(
        string='Solo productos publicados en la web',
        default=False,
        help='Limita el catálogo a los productos marcados como publicados en la tienda web. '
             'Solo disponible si el módulo Website eCommerce está instalado.',
    )
    website_sale_installed = fields.Boolean(
        string='Website eCommerce instalado',
        compute='_compute_website_sale_installed',
        help='Campo técnico: detecta si website_sale está instalado para mostrar '
             'u ocultar el filtro "Solo productos publicados en la web".',
    )

    # ────────────────────────────────────────────────────────────────────────
    #  Detección dinámica de módulos opcionales (soft dependency)
    # ────────────────────────────────────────────────────────────────────────
    @api.depends_context('uid')
    def _compute_website_sale_installed(self):
        """
        Detecta si website_sale está instalado consultando ir.module.module.
        Es la forma estándar en Odoo de hacer "soft dependencies": el módulo
        se instala sin website_sale, pero si existe activamos el filtro.
        """
        installed = bool(self.env['ir.module.module'].sudo().search_count([
            ('name', '=', 'website_sale'),
            ('state', '=', 'installed'),
        ]))
        for rec in self:
            rec.website_sale_installed = installed
    only_can_be_sold = fields.Boolean(
        string='Solo productos vendibles',
        default=True,
        help='Excluye los productos con “Puede venderse” desmarcado.',
    )

    # ── Tarifa ──────────────────────────────────────────────────────────────
    pricelist_id = fields.Many2one(
        'product.pricelist', string='Tarifa',
        required=True,
        default=lambda s: s._default_pricelist(),
    )

    # ── Estilo y presentación ───────────────────────────────────────────────
    style = fields.Selection(
        [
            ('1', 'Estilo 1 — Tabla con imagen pequeña'),
            ('2', 'Estilo 2 — Ficha completa por producto'),
            ('3', 'Estilo 3 — Rejilla 3 columnas'),
            ('4', 'Estilo 4 — Cuadrícula configurable'),
        ],
        default='1', required=True, string='Estilo de diseño',
    )
    boxes_per_row = fields.Selection(
        [('2', '2 columnas'), ('3', '3 columnas'), ('4', '4 columnas')],
        default='3', string='Columnas por fila (solo estilo 4)',
    )
    image_size = fields.Selection(
        [('small', 'Pequeño'), ('medium', 'Mediano'), ('large', 'Grande')],
        default='medium', string='Tamaño de imagen',
    )

    # Campos a mostrar
    show_price = fields.Boolean(string='Mostrar precio', default=True)
    show_description = fields.Boolean(string='Mostrar descripción', default=True)
    show_reference = fields.Boolean(string='Mostrar referencia interna', default=True)
    show_uom = fields.Boolean(string='Mostrar unidad de medida', default=False)
    show_category = fields.Boolean(string='Mostrar categoría', default=False)

    # Cabecera y pie
    header_html = fields.Html(
        string='Cabecera personalizada',
        sanitize=False,
        help='Texto/HTML que se pintará en la primera página antes del listado de productos.',
    )
    footer_html = fields.Html(
        string='Pie personalizado',
        sanitize=False,
        help='Texto/HTML que se pintará al final, tras el listado de productos.',
    )
    header_pdf = fields.Binary(string='PDF de portada (opcional)')
    header_pdf_filename = fields.Char(string='Nombre portada')
    footer_pdf = fields.Binary(string='PDF de contraportada (opcional)')
    footer_pdf_filename = fields.Char(string='Nombre contraportada')

    # ────────────────────────────────────────────────────────────────────────
    #  Defaults
    # ────────────────────────────────────────────────────────────────────────
    @api.model
    def _default_pricelist(self):
        """Toma la tarifa por defecto de la empresa del usuario, si existe."""
        company = self.env.company
        pricelist = self.env['product.pricelist'].search(
            [('currency_id', '=', company.currency_id.id)],
            limit=1,
        )
        return pricelist.id if pricelist else False

    # ────────────────────────────────────────────────────────────────────────
    #  Cálculo de productos a incluir
    # ────────────────────────────────────────────────────────────────────────
    def _compute_products(self):
        """Construye y ejecuta el dominio de búsqueda según los filtros."""
        self.ensure_one()
        domain = []

        if self.filter_mode == 'by_products':
            if not self.product_ids:
                raise UserError(_('Has elegido "Productos concretos" pero no has seleccionado ninguno.'))
            domain.append(('id', 'in', self.product_ids.ids))

        elif self.filter_mode == 'by_categories':
            if not self.category_ids:
                raise UserError(_('Has elegido "Por categorías" pero no has seleccionado ninguna.'))
            # child_of permite arrastrar las subcategorías también
            domain.append(('categ_id', 'child_of', self.category_ids.ids))

        if self.only_can_be_sold:
            domain.append(('sale_ok', '=', True))

        # Filtro opcional: solo aplicable si website_sale está instalado y
        # el campo `is_published` existe en product.template (lo añade website_sale).
        if self.only_website_published and 'is_published' in self.env['product.template']._fields:
            domain.append(('is_published', '=', True))

        products = self.env['product.template'].search(domain)
        if not products:
            raise UserError(_('Los filtros aplicados no devuelven ningún producto. Revisa las opciones.'))
        return products

    # ────────────────────────────────────────────────────────────────────────
    #  Acción principal: generar el catálogo
    # ────────────────────────────────────────────────────────────────────────
    def action_generate(self):
        self.ensure_one()
        products = self._compute_products()

        catalogue = self.env['product.catalogue'].create({
            'name': self.name,
            'product_ids': [(6, 0, products.ids)],
            'pricelist_id': self.pricelist_id.id,
            'style': self.style,
            'boxes_per_row': self.boxes_per_row,
            'image_size': self.image_size,
            'show_price': self.show_price,
            'show_description': self.show_description,
            'show_reference': self.show_reference,
            'show_uom': self.show_uom,
            'show_category': self.show_category,
            'header_html': self.header_html,
            'footer_html': self.footer_html,
            'header_pdf': self.header_pdf,
            'header_pdf_filename': self.header_pdf_filename,
            'footer_pdf': self.footer_pdf,
            'footer_pdf_filename': self.footer_pdf_filename,
        })
        catalogue.action_generate_pdf()

        # Abre el registro recién creado en formulario
        return {
            'type': 'ir.actions.act_window',
            'name': _('Catálogo generado'),
            'res_model': 'product.catalogue',
            'res_id': catalogue.id,
            'view_mode': 'form',
            'target': 'current',
        }
