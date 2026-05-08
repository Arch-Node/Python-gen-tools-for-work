(function () {
    const searchBox = document.getElementById('search');
    const treeRoot = document.getElementById('tree-root');
    const noResults = document.getElementById('no-results');
    const expandBtn = document.getElementById('expand-all');
    const collapseBtn = document.getElementById('collapse-all');

    const allNodes = Array.from(treeRoot.querySelectorAll('[data-search]'));
    const allDetails = Array.from(treeRoot.querySelectorAll('details'));

    function setAllDetails(openValue) {
        allDetails.forEach(function (d) { d.open = openValue; });
    }

    function filterTree(query) {
        const q = query.trim().toLowerCase();
        let visibleCount = 0;

        if (!q) {
            allNodes.forEach(function (node) { node.classList.remove('hidden'); });
            noResults.style.display = 'none';
            return;
        }

        allNodes.forEach(function (node) {
            const haystack = (node.getAttribute('data-search') || '').toLowerCase();
            const isMatch = haystack.indexOf(q) >= 0;
            node.classList.toggle('hidden', !isMatch);
            if (isMatch) {
                visibleCount += 1;
                let p = node.parentElement;
                while (p) {
                    if (p.tagName && p.tagName.toLowerCase() === 'details') {
                        p.open = true;
                        p.classList.remove('hidden');
                    }
                    p = p.parentElement;
                }
            }
        });

        noResults.style.display = visibleCount === 0 ? 'block' : 'none';
    }

    searchBox.addEventListener('input', function (event) {
        filterTree(event.target.value);
    });

    expandBtn.addEventListener('click', function () {
        setAllDetails(true);
    });

    collapseBtn.addEventListener('click', function () {
        setAllDetails(false);
    });
})();
