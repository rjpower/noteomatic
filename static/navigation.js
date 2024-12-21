document.addEventListener('keydown', function (e) {
    if (e.key === 'Backspace') {
        // Go back to home page
        window.location.href = '/';
    } else if (e.key === 'ArrowLeft') {
        const prev = document.getElementById('prev-note');
        if (prev) {
            window.location.href = prev.href;
            // history.replaceState({}, '', prev.href);
            // window.location.replace
        }
    } else if (e.key === 'ArrowRight') {
        const next = document.getElementById('next-note');
        if (next) {
            window.location.href = next.href;
            // history.replaceState({}, '', next.href);
            // window.location.replace(next.href);
        }
    } else if (e.key === '/') {
        // Focus on search input
        const searchInput = document.querySelector('#search-form input[type="text"]');
        if (searchInput) {
            e.preventDefault();
            searchInput.focus();
        }
    }
});

document.addEventListener('DOMContentLoaded', function () {
    const searchForm = document.getElementById('search-form');
    if (searchForm) {
        searchForm.addEventListener('submit', function (e) {
            e.preventDefault();
            const query = searchForm.querySelector('input[type="text"]').value;
            window.location.href = `/search?q=${encodeURIComponent(query)}`;
        });
    }
});
