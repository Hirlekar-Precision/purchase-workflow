# Copyright 2021 Jacques-Etienne Baudoux (BCIM) <je@bcim.be>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

import pytz

from odoo import fields, models
from odoo.osv import expression
from odoo.tools import groupby


class StockMove(models.Model):
    _inherit = "stock.move"

    def _purchase_split_date_get_group_keys(self):
        tz = self.picking_type_id.warehouse_id.partner_id.tz or self.env.user.tz
        wh_tz = pytz.timezone(tz or "UTC")
        date_planned_tz = self.date_deadline.astimezone(pytz.utc).astimezone(wh_tz)
        date = date_planned_tz.date()
        # Split date value to obtain only the attributes year, month and day
        key = ({"date_planned": fields.Date.to_string(date)},)
        return key

    def _search_picking_for_assignation_domain(self):
        domain = super()._search_picking_for_assignation_domain()
        if self.env.context.get("purchase_delivery_split_date"):
            key = self._purchase_split_date_get_group_keys()
            tz = self.picking_type_id.warehouse_id.partner_id.tz or self.env.user.tz
            domain = expression.AND(
                [domain, self.picking_id._purchase_split_date_assign_domain(key, tz)]
            )
        return domain

    def write(self, vals):
        res = super().write(vals)
        if "date_deadline" in vals:
            self._purchase_split_by_date(vals["date_deadline"])
        return res

    def _purchase_split_by_date(self, new_deadline):
        # Hirlekar patch: a cleared deadline (falsy) has no day to split by, and
        # _purchase_split_date_get_group_keys would do `False.astimezone(...)`
        # (AttributeError: 'bool' object has no attribute 'astimezone'). Skip.
        if not new_deadline:
            return
        po_moves = self.filtered(
            lambda m: m.purchase_line_id and m.state not in ("done", "cancel")
        )
        if not po_moves:
            return
        po_moves.date = new_deadline
        for picking, moves_list in groupby(po_moves, lambda m: m.picking_id):
            if picking.printed:
                # Do not split by date anymore
                continue
            moves = self.browse().concat(*moves_list)
            other_moves = picking.move_ids - moves

            if not other_moves:
                # All moves on this picking are changing date — check if we
                # can just re-date the picking instead of cancel+recreate.
                domain = moves[0].with_context(
                    purchase_delivery_split_date=True,
                )._search_picking_for_assignation_domain()
                domain.append(("id", "!=", picking.id))
                existing = self.env["stock.picking"].search(domain, limit=1)
                if not existing:
                    picking.scheduled_date = new_deadline
                    picking.date_deadline = new_deadline
                    continue

            reserved_moves = moves.filtered(
                lambda m: m.state in ("partially_available", "assigned")
            )
            reserved_moves._do_unreserve()
            # _do_unreserve skips moves/lines with picked=True — detach those
            # lines explicitly so they don't stay on a cancelled picking.
            remaining_lines = moves.move_line_ids
            moves.picking_id = False
            remaining_lines.picking_id = False
            if picking.move_ids:
                picking._compute_scheduled_date()
                picking._compute_date_deadline()
            else:
                picking.state = "cancel"
            moves.with_context(purchase_delivery_split_date=True)._assign_picking()
            for move in moves:
                move.move_line_ids.picking_id = move.picking_id
            reserved_moves._action_assign()

    def _get_new_picking_values(self):
        vals = super()._get_new_picking_values()
        if self.env.context.get("purchase_delivery_split_date"):
            is_dropship = all([move._is_dropshipped() for move in self])
            if not vals.get("partner_id") or is_dropship:
                vals["partner_id"] = fields.first(self.purchase_line_id.partner_id).id
        return vals

    def _assign_picking_values(self, picking):
        vals = super()._assign_picking_values(picking)
        # The core function will remove the partner from the picking if it is
        # different than the one on the moves (Destination Address).
        # For dropshipping the partner on the pick is the contact !
        if self.env.context.get("purchase_delivery_split_date"):
            if "partner_id" in vals.keys():
                vals.pop("partner_id")
        return vals
