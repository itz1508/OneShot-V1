"""Doc cross-reference pins (directive v6.0.11 D-01)."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
README = ROOT / 'README.md'


def test_readme_links_to_e2e_matrix():
    assert '`docs/E2E_MATRIX.md`' in README.read_text(), (
        'README.md must reference docs/E2E_MATRIX.md so operators find the full E2E map')


def test_e2e_matrix_actually_exists():
    """Guard against the link rotting."""
    assert (ROOT / 'docs' / 'E2E_MATRIX.md').is_file()


def test_readme_links_to_authoritative_docs():
    """Pin the four README → docs links that already exist so future README
    churn cannot silently drop any of them."""
    src = README.read_text()
    for ref in ('docs/MODEL_INTEGRATIONS.md',
                'docs/PRE_SEND_CONTEXT_REVIEW.md',
                'docs/SYSTEM_BACKGROUND.md',
                'docs/INSTALL_RELEASE_GATES.md',
                'docs/E2E_MATRIX.md'):
        assert ref in src, f'README.md must reference {ref}'
