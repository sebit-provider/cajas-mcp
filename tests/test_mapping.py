from __future__ import annotations

import unittest

from cajas_mcp.adapters.mapping import infer_coa_column_mapping, infer_column_mapping


class MappingTests(unittest.TestCase):
    def test_korean_aliases(self) -> None:
        voucher = "\uc804\ud45c\ubc88\ud638"
        date = "\uc77c\uc790"
        side = "\ucc28\ub300"
        account_code = "\uacc4\uc815\ucf54\ub4dc"
        amount = "\uae08\uc561"
        memo = "\uc801\uc694"
        mapping, _, _ = infer_column_mapping([voucher, date, side, account_code, amount, memo])
        self.assertEqual(mapping[voucher], "voucher_number")
        self.assertEqual(mapping[date], "transaction_date")
        self.assertEqual(mapping[side], "line_side")
        self.assertEqual(mapping[account_code], "account_code")
        self.assertEqual(mapping[amount], "amount")

    def test_english_aliases(self) -> None:
        mapping, _, _ = infer_column_mapping(["voucher no", "posting date", "dr/cr", "account name", "amount"])
        self.assertEqual(mapping["voucher no"], "voucher_number")
        self.assertEqual(mapping["posting date"], "transaction_date")
        self.assertEqual(mapping["account name"], "account_name")

    def test_ambiguous_account_column_requires_choice(self) -> None:
        _, candidates, _ = infer_column_mapping(["\uacc4\uc815"])
        row = candidates[0]
        self.assertTrue(row["requires_choice"])
        self.assertGreaterEqual(len(row["candidates"]), 2)

    def test_missing_date_and_amount_warns(self) -> None:
        _, _, warnings = infer_column_mapping(["\uacc4\uc815\ucf54\ub4dc", "\uc801\uc694"])
        joined = "\n".join(warnings)
        self.assertIn("transaction_date", joined)
        self.assertIn("amount/debit/credit", joined)

    def test_debit_credit_split_format(self) -> None:
        mapping, _, _ = infer_column_mapping(["date", "account code", "debit amount", "credit amount"])
        self.assertEqual(mapping["debit amount"], "debit_amount")
        self.assertEqual(mapping["credit amount"], "credit_amount")

    def test_coa_korean_headers(self) -> None:
        code = "\uacc4\uc815\ucf54\ub4dc"
        name = "\uacc4\uc815\uacfc\ubaa9"
        english = "\uc601\ubb38\uacc4\uc815\uba85"
        mapping, _, warnings = infer_coa_column_mapping([code, name, english])
        self.assertEqual(mapping[code], "code")
        self.assertEqual(mapping[english], "name_en")
        self.assertFalse(any("code" in warning for warning in warnings))

    def test_coa_ambiguous_name_requires_choice(self) -> None:
        _, candidates, _ = infer_coa_column_mapping(["account name"])
        self.assertTrue(candidates[0]["requires_choice"])


if __name__ == "__main__":
    unittest.main()
