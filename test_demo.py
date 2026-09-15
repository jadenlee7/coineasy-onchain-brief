"""Meaningful offline regression checks for the public demonstration."""
import unittest
import json
import tempfile
from pathlib import Path
from app import build_payload, build_manual_payload
from fixtures import NOW, digest_at
from history import snapshot_digest
from reader_context import observation_label, short_address


class ResearchSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = build_payload()["scenarios"]

    def test_matching_prior_day_yields_percentage_point_change(self):
        row = self.data["comparable"]["digest"]["perp_rows"][0]
        self.assertEqual(row["long_pct_delta_pp"], 2.0)
        self.assertEqual(self.data["comparable"]["digest"]["meme_rows"][0]["observed_positive_streak"], 7)

    def test_missing_day_does_not_compare_two_days_ago(self):
        sample = self.data["missing"]
        self.assertIsNone(sample["digest"]["perp_rows"][0]["long_pct_delta_pp"])
        self.assertEqual(sample["digest"]["comparison_context"]["positioning"], "no_previous_snapshot")
        self.assertEqual(sample["digest"]["meme_rows"][0]["observed_positive_streak"], 1)
        self.assertEqual(sample["coverage"][-2]["positioning"], "missing")

    def test_changed_cohort_cannot_be_compared(self):
        sample = self.data["cohort"]
        self.assertIsNone(sample["digest"]["perp_rows"][0]["long_pct_delta_pp"])
        self.assertEqual(sample["digest"]["comparison_context"]["positioning"], "cohort_changed")

    def test_recovery_is_not_a_regular_observation(self):
        sample = self.data["recovery"]
        self.assertEqual(sample["coverage"][-1]["positioning"], "non_scheduled")
        self.assertIn("not a scheduled", sample["labels"]["en"]["observation"])
        self.assertIsNone(sample["digest"]["perp_rows"][0]["long_pct_delta_pp"])

    def test_invalid_time_not_replaced_with_render_time(self):
        sample = self.data["unknown"]
        self.assertIn("unobserved", sample["labels"]["en"]["observation"])
        self.assertEqual(sample["coverage"][-1]["positioning"], "missing")
        digest = digest_at(NOW)
        digest.observed_at = "invalid"
        with self.assertRaises(ValueError):
            snapshot_digest(digest)

    def test_unknown_liquidity_is_not_zero(self):
        self.assertIsNone(self.data["partial"]["digest"]["meme_rows"][1]["liquidity"])

        self.assertFalse(self.data["partial"]["digest"]["meme_rows"][1]["verified_meme"])
        self.assertEqual(self.data["partial"]["digest"]["token_mode"], "candidate")

    def test_chain_address_identity_and_synthetic_mode(self):
        token = self.data["comparable"]["digest"]["meme_rows"][0]
        self.assertEqual(len(token["token_address"]), 42)
        self.assertEqual(token["chain"], "base")
        self.assertEqual(short_address("base", "bad-address"), "주소 미관측")
        self.assertIn("Synthetic", build_payload()["data_mode"])

    def test_legacy_purpose_is_not_claimed_scheduled(self):
        digest = digest_at(NOW, kind="unknown")
        self.assertIn("purpose unconfirmed", observation_label(digest, english=True))


class ManualInputTests(unittest.TestCase):
    def render(self, snapshot):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "snapshot.json"
            path.write_text(json.dumps(snapshot))
            return build_manual_payload(path)

    def test_manual_never_claims_regular_observation(self):
        payload = self.render(snapshot_digest(digest_at(NOW)))
        self.assertEqual(payload["data_mode"], "manual_api_observation")
        self.assertEqual(payload["scenarios"]["manual"]["digest"]["observation_kind"], "manual")
        self.assertEqual(payload["scenarios"]["manual"]["coverage"], [])

    def test_invalid_cohort_is_rejected(self):
        source = snapshot_digest(digest_at(NOW)); source["perp_cohort"] = "retail"
        with self.assertRaises(ValueError): self.render(source)

    def test_errors_hide_stale_rows_and_preserve_unavailability(self):
        source = snapshot_digest(digest_at(NOW)); source["section_errors"] = {"positioning": "raw private error", "memecoin": "raw error"}
        data = self.render(source)["scenarios"]["manual"]
        self.assertEqual(data["digest"]["perp_rows"], [])
        self.assertEqual(data["digest"]["meme_rows"], [])
        self.assertNotIn("raw private", json.dumps(data))
        self.assertIn("unavailable", data["labels"]["en"]["positioning"])

    def test_address_is_never_truncated_or_coerced(self):
        for address in [None, "0x" + "1" * 200]:
            source = snapshot_digest(digest_at(NOW)); source["meme_rows"][0]["token_address"] = address
            with self.assertRaises(ValueError): self.render(source)

    def test_unverified_or_missing_liquidity_not_accepted_as_verified(self):
        for field, value in [("verified_meme", False), ("liquidity", None)]:
            source = snapshot_digest(digest_at(NOW)); source["meme_rows"][0][field] = value
            with self.assertRaises(ValueError): self.render(source)


if __name__ == "__main__":
    unittest.main()
