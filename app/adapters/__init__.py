from app.adapters import generic_html, greenhouse, indeed, lever, linkedin

ADAPTERS = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "generic_html": generic_html.fetch,
    "linkedin": linkedin.fetch,
    "indeed": indeed.fetch,
}
