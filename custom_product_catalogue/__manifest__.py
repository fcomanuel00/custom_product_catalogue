# -*- coding: utf-8 -*-
# Part of Framarketing. See LICENSE file for full copyright and licensing details.
{
    'name': 'Product Catalogue Generator',
    'version': '19.0.1.3.1',
    'category': 'Sales/Sales',
    'summary': 'Generate stylish product catalogue PDFs with 4 designs, custom header/footer, variants support, pricelist-aware prices and email sending',
    'description': """
Product Catalogue Generator
============================
Create flexible, professional product catalogue PDFs from your Odoo catalog.

Key features
------------
* 4 ready-to-use layouts (table, full card, category grid, configurable grid)
* Filter by product, by category, or show all — with a simple wizard
* Choose which pricelist applies to the printed prices
* Support for product variants (attributes shown under each parent product)
* Variant images with automatic fallback to parent image
* Custom HTML header and footer, plus optional cover & back-cover PDFs
* Keep a history of every generated catalogue (re-download, re-send anytime)
* Send the PDF to customers by email directly from the catalogue record
* Fine-grained access control: Users (read-only) vs Managers (generate & send)
* Clean top-level menu — no clutter in existing apps

Built for Odoo 19 Community.

Optional: if *Website eCommerce* (website_sale) is installed, an extra
filter appears to include only products published on the web. No extra
setup required.
    """,
    'author': 'Framarketing',
    'website': 'https://framarketing.es',
    'support': 'info@framarketing.es',
    'license': 'OPL-1',
    'price': 89.00,
    'currency': 'EUR',
    'images': ['static/description/banner.png'],
    'depends': [
        'product',
        'sale_management',
        'mail',
    ],
    'data': [
        # Security first
        'security/catalogue_security.xml',
        'security/ir.model.access.csv',

        # Reports FIRST: the email template references the report
        'reports/report_action.xml',
        'reports/report_style_common.xml',
        'reports/report_style_1.xml',
        'reports/report_style_2.xml',
        'reports/report_style_3.xml',
        'reports/report_style_4.xml',

        # Data (mail template references the report loaded above)
        'data/mail_template_data.xml',

        # Views
        'views/product_catalogue_views.xml',
        'wizards/product_catalogue_wizard_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
