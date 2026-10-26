from opspilot.processing.drain_parser import build_miner


def mine(miner, msg):
    r = miner.add_log_message(msg)
    return r["cluster_id"], r["template_mined"]


def test_numeric_variants_share_one_template():
    m = build_miner()
    a = mine(m, "QueuePool limit of size 2 overflow 0 reached, connection timed out, timeout 1.00")
    b = mine(m, "QueuePool limit of size 5 overflow 0 reached, connection timed out, timeout 2.50")
    assert a[0] == b[0]
    assert "<NUM>" in b[1]


def test_durations_are_masked():
    m = build_miner()
    a = mine(m, "payment-gateway timed out after 3.0s")
    b = mine(m, "payment-gateway timed out after 2.5s")
    assert a[0] == b[0]
    assert b[1] == "payment-gateway timed out after <NUM>"


def test_different_errors_get_different_templates():
    m = build_miner()
    ids = {
        mine(m, "TypeError: 'NoneType' object is not subscriptable")[0],
        mine(m, "MemoryError: Cannot allocate memory: worker heap exhausted")[0],
        mine(m, "could not translate host name 'db-prod-typo' to address: Name or service not known")[0],
        mine(m, "request completed")[0],
    }
    assert len(ids) == 4


def test_state_survives_restart(tmp_path):
    path = str(tmp_path / "drain.bin")
    first = build_miner(path)
    cid, _ = mine(first, "request completed")
    first.save_state("test")
    second = build_miner(path)
    assert mine(second, "request completed")[0] == cid
