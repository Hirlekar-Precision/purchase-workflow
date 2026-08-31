# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
# Hirlekar fork patch — regression test for a cleared (falsy) deadline.
#
# Uses a plain TransactionCase (not BaseCommon) so it runs on the Hirlekar
# prod-restored test database, where BaseCommon's fixture setup fails.
from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSplitByDateNullDeadline(TransactionCase):
    """`_purchase_split_by_date` must no-op on a cleared (falsy) deadline instead
    of crashing in `_purchase_split_date_get_group_keys` (`False.astimezone(...)`
    -> AttributeError: 'bool' object has no attribute 'astimezone')."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env["res.partner"].create({"name": "Split Null Vendor"})
        cls.product = cls.env["product.product"].create({
            "name": "Split Null Widget",
            "type": "consu",
            "is_storable": True,
            "standard_price": 10,
        })
        cls.po = cls.env["purchase.order"].create({
            "partner_id": cls.vendor.id,
            "order_line": [Command.create({
                "product_id": cls.product.id,
                "product_uom": cls.product.uom_id.id,
                "name": cls.product.name,
                "price_unit": 10,
                "product_qty": 5.0,
            })],
        })
        cls.po.button_confirm()

    def test_split_by_date_noop_on_falsy_deadline(self):
        moves = self.po.picking_ids.move_ids.filtered("purchase_line_id")
        self.assertTrue(moves, "the confirmed PO should have a receipt move")
        # Previously raised 'bool' object has no attribute 'astimezone'.
        self.assertFalse(moves._purchase_split_by_date(False))
