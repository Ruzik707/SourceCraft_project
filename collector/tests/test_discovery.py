from collector.discovery import discover_open_repos


class FakePlatformClient:
    def __init__(self, repos):
        self._repos = repos

    def paginate(self, operation_key, *, path_params=None, query=None, max_pages=200):
        return self._repos


def test_discover_open_repos_filters_to_public_only():
    repos = [
        {
            "id": "repo-1", "slug": "public-repo", "visibility": "public",
            "organization": {"slug": "acme"},
            "clone_url": {"ssh": "ssh://ssh.sourcecraft.dev/acme/public-repo.git", "https": "https://sourcecraft.dev/acme/public-repo.git"},
        },
        {
            "id": "repo-2", "slug": "private-repo", "visibility": "private",
            "organization": {"slug": "acme"},
            "clone_url": {"ssh": "ssh://ssh.sourcecraft.dev/acme/private-repo.git"},
        },
    ]
    refs = discover_open_repos(FakePlatformClient(repos))

    assert len(refs) == 1
    assert refs[0].owner == "acme"
    assert refs[0].name == "public-repo"
    assert refs[0].clone_url == "ssh://ssh.sourcecraft.dev/acme/public-repo.git"
    assert refs[0].gitrepo_id == "repo-1"


def test_discover_open_repos_prefers_ssh_over_https():
    repos = [{
        "id": "repo-3", "slug": "r", "visibility": "public",
        "organization": {"slug": "acme"},
        "clone_url": {"ssh": "ssh://x", "https": "https://y"},
    }]
    refs = discover_open_repos(FakePlatformClient(repos))
    assert refs[0].clone_url == "ssh://x"


def test_discover_open_repos_skips_entries_missing_required_fields():
    repos = [
        {"id": "no-clone-url", "slug": "r", "visibility": "public", "organization": {"slug": "acme"}, "clone_url": {}},
        {"id": "no-org", "slug": "r2", "visibility": "public", "organization": {}, "clone_url": {"ssh": "ssh://x"}},
    ]
    refs = discover_open_repos(FakePlatformClient(repos))
    assert refs == []
