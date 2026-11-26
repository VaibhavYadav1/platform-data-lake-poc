"""write_crm_export: an hourly export must not be lost to a late, skipped or failed tick. No GCS and no database:
the bucket is a dict of folder -> complete?"""

from datetime import datetime, timezone

import pytest

from simulator import crm_export, tick


class FakeBucket:
    def __init__(self, done=()):
        self.done = set(done)      # export_ts strings that already have a manifest
        self.written = []          # export_ts strings in the order they were uploaded

    def install(self, monkeypatch):
        monkeypatch.setattr(crm_export, "export_exists",
                            lambda b, p, t: t.strftime("%Y%m%dT%H%M%SZ") in self.done)

        def fake_upload(b, p, t, files):
            ts = t.strftime("%Y%m%dT%H%M%SZ")
            self.written.append(ts)
            self.done.add(ts)
            return "gs://%s/%s/export_ts=%s" % (b, p, ts)
        monkeypatch.setattr(crm_export, "upload_to_gcs", fake_upload)
        return self


def at(h, m=0):
    return datetime(2026, 11, 26, h, m, tzinfo=timezone.utc)


def test_writes_this_hours_export_on_a_late_tick(monkeypatch):
    bucket = FakeBucket(done={"20261126T060000Z", "20261126T050000Z", "20261126T040000Z", "20261126T030000Z"}).install(monkeypatch)
    out = tick.write_crm_export("b", "crm", at(7, 17))      # the 07:00 tick was lost; this is the 07:15 tick
    assert bucket.written == ["20261126T070000Z"] and out.endswith("export_ts=20261126T070000Z")


def test_second_tick_in_the_same_hour_writes_nothing(monkeypatch):
    bucket = FakeBucket().install(monkeypatch)
    tick.write_crm_export("b", "crm", at(7, 2))
    again = tick.write_crm_export("b", "crm", at(7, 7))
    assert again == "up-to-date" and len([t for t in bucket.written if t == "20261126T070000Z"]) == 1


def test_never_rewrites_a_complete_export(monkeypatch):
    bucket = FakeBucket(done={"20261126T070000Z"}).install(monkeypatch)
    tick.write_crm_export("b", "crm", at(7, 30))
    assert "20261126T070000Z" not in bucket.written


def test_catches_up_missed_hours_oldest_first_and_no_further_back(monkeypatch):
    bucket = FakeBucket().install(monkeypatch)
    tick.write_crm_export("b", "crm", at(10, 3))
    assert bucket.written == ["20261126T070000Z", "20261126T080000Z", "20261126T090000Z", "20261126T100000Z"]
    assert len(bucket.written) == tick.CRM_CATCHUP_HOURS + 1


def test_a_half_written_folder_is_written_again(monkeypatch):
    # CSVs uploaded, the tick died before the manifest: no manifest, so the hour counts as missing
    bucket = FakeBucket(done=set()).install(monkeypatch)
    tick.write_crm_export("b", "crm", at(7, 0))
    assert "20261126T070000Z" in bucket.written
