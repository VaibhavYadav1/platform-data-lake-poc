import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import check_env_diff as c  # noqa: E402


def make(tmp_path, files):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return tmp_path


def test_clean_repo_passes(tmp_path):
    make(tmp_path, {
        "terraform/env/dev.tfvars": 'project_id = "a"\nenv = "dev"\n',
        "terraform/env/int.tfvars": 'project_id = "a"\nenv = "int"\n',
        "terraform/env/main.tf": "",
    })
    errors, _ = c.check(tmp_path)
    assert errors == []


def test_missing_int_is_skipped(tmp_path):
    make(tmp_path, {"terraform/env/dev.tfvars": 'env = "dev"\n'})
    errors, notes = c.check(tmp_path)
    assert errors == [] and any("int.tfvars" in n for n in notes)


def test_env_specific_tf_file_fails(tmp_path):
    make(tmp_path, {"terraform/env/main.dev.tf": "", "terraform/env/dev.tfvars": ""})
    errors, _ = c.check(tmp_path)
    assert len(errors) == 1 and "main.dev.tf" in errors[0]


def test_key_drift_fails(tmp_path):
    make(tmp_path, {
        "terraform/env/dev.tfvars": 'a = 1\nb = 2\n',
        "terraform/env/int.tfvars": 'a = 1\n',
    })
    errors, _ = c.check(tmp_path)
    assert len(errors) == 1 and "['b']" in errors[0]
