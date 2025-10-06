// NADB Blog JavaScript

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    initializeMarkdown();
    initializeTooltips();
    initializeFormValidation();
});

// Markdown rendering for post content
function initializeMarkdown() {
    const markdownContent = document.querySelector('.markdown-content');
    if (markdownContent && typeof marked !== 'undefined') {
        const rawContent = markdownContent.textContent || markdownContent.innerText;
        
        // Configure marked options
        marked.setOptions({
            highlight: function(code, lang) {
                if (typeof hljs !== 'undefined' && lang && hljs.getLanguage(lang)) {
                    try {
                        return hljs.highlight(code, { language: lang }).value;
                    } catch (err) {
                        console.warn('Highlight.js error:', err);
                    }
                }
                return code;
            },
            breaks: true,
            gfm: true
        });
        
        // Render markdown
        markdownContent.innerHTML = marked.parse(rawContent);
        
        // Highlight code blocks
        if (typeof hljs !== 'undefined') {
            markdownContent.querySelectorAll('pre code').forEach((block) => {
                hljs.highlightElement(block);
            });
        }
    }
}

// Initialize tooltips and interactive elements
function initializeTooltips() {
    // Add click-to-copy functionality for code blocks
    document.querySelectorAll('pre code').forEach(function(codeBlock) {
        const button = document.createElement('button');
        button.className = 'copy-code-btn';
        button.innerHTML = '<i class="fas fa-copy"></i>';
        button.title = 'Copy code';
        
        button.addEventListener('click', function() {
            navigator.clipboard.writeText(codeBlock.textContent).then(function() {
                showToast('Code copied to clipboard!', 'success');
                button.innerHTML = '<i class="fas fa-check"></i>';
                setTimeout(() => {
                    button.innerHTML = '<i class="fas fa-copy"></i>';
                }, 2000);
            }).catch(function() {
                showToast('Failed to copy code', 'error');
            });
        });
        
        const pre = codeBlock.parentElement;
        pre.style.position = 'relative';
        pre.appendChild(button);
    });
}

// Form validation
function initializeFormValidation() {
    const forms = document.querySelectorAll('.post-form');
    
    forms.forEach(function(form) {
        form.addEventListener('submit', function(e) {
            const title = form.querySelector('#title');
            const content = form.querySelector('#content');
            
            let isValid = true;
            let errors = [];
            
            // Validate title
            if (!title.value.trim()) {
                errors.push('Title is required');
                title.style.borderColor = 'var(--danger)';
                isValid = false;
            } else {
                title.style.borderColor = '';
            }
            
            // Validate content
            if (!content.value.trim()) {
                errors.push('Content is required');
                content.style.borderColor = 'var(--danger)';
                isValid = false;
            } else {
                content.style.borderColor = '';
            }
            
            // Show errors if any
            if (!isValid) {
                e.preventDefault();
                showToast(errors.join(', '), 'error');
            }
        });
        
        // Real-time validation
        const inputs = form.querySelectorAll('input[required], textarea[required]');
        inputs.forEach(function(input) {
            input.addEventListener('blur', function() {
                if (!input.value.trim()) {
                    input.style.borderColor = 'var(--danger)';
                } else {
                    input.style.borderColor = '';
                }
            });
            
            input.addEventListener('input', function() {
                if (input.style.borderColor === 'var(--danger)' && input.value.trim()) {
                    input.style.borderColor = '';
                }
            });
        });
    });
}

// Toast notification system
function showToast(message, type = 'success') {
    const toast = document.getElementById('toast');
    if (!toast) return;
    
    // Set message and type
    toast.textContent = message;
    toast.className = `toast ${type}`;
    
    // Show toast
    toast.classList.add('show');
    
    // Hide after 3 seconds
    setTimeout(function() {
        toast.classList.remove('show');
    }, 3000);
}

// Delete post confirmation
function deletePost(postId) {
    if (confirm('Are you sure you want to delete this post? This action cannot be undone.')) {
        // Create a form and submit it
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = `/delete/${postId}`;
        
        // Add CSRF token if available
        const csrfToken = document.querySelector('meta[name="csrf-token"]');
        if (csrfToken) {
            const tokenInput = document.createElement('input');
            tokenInput.type = 'hidden';
            tokenInput.name = 'csrf_token';
            tokenInput.value = csrfToken.getAttribute('content');
            form.appendChild(tokenInput);
        }
        
        document.body.appendChild(form);
        form.submit();
    }
}

// Create backup
function createBackup() {
    const button = document.querySelector('.backup-btn');
    if (!button) return;
    
    // Disable button and show loading
    const originalText = button.innerHTML;
    button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Creating Backup...';
    button.disabled = true;
    
    fetch('/api/backup', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast(`Backup created successfully! ID: ${data.backup_id}`, 'success');
        } else {
            showToast(`Backup failed: ${data.error}`, 'error');
        }
    })
    .catch(error => {
        console.error('Backup error:', error);
        showToast('Backup failed: Network error', 'error');
    })
    .finally(() => {
        // Restore button
        button.innerHTML = originalText;
        button.disabled = false;
    });
}

// Auto-save for forms (draft functionality)
function initializeAutoSave() {
    const forms = document.querySelectorAll('.post-form');
    
    forms.forEach(function(form) {
        const title = form.querySelector('#title');
        const content = form.querySelector('#content');
        
        if (!title || !content) return;
        
        let autoSaveTimeout;
        
        function autoSave() {
            const formData = {
                title: title.value,
                content: content.value,
                author: form.querySelector('#author')?.value || 'Anonymous',
                tags: form.querySelector('#tags')?.value || ''
            };
            
            // Save to localStorage
            localStorage.setItem('nadb_blog_draft', JSON.stringify(formData));
            
            // Show subtle indication
            const indicator = document.createElement('div');
            indicator.textContent = 'Draft saved';
            indicator.style.cssText = `
                position: fixed;
                top: 10px;
                right: 10px;
                background: var(--success);
                color: white;
                padding: 0.5rem 1rem;
                border-radius: var(--border-radius);
                font-size: 0.875rem;
                opacity: 0.8;
                z-index: 1000;
            `;
            document.body.appendChild(indicator);
            
            setTimeout(() => {
                document.body.removeChild(indicator);
            }, 2000);
        }
        
        function scheduleAutoSave() {
            clearTimeout(autoSaveTimeout);
            autoSaveTimeout = setTimeout(autoSave, 2000); // Save after 2 seconds of inactivity
        }
        
        // Attach auto-save to input events
        [title, content].forEach(function(input) {
            input.addEventListener('input', scheduleAutoSave);
        });
        
        // Load draft on page load
        const savedDraft = localStorage.getItem('nadb_blog_draft');
        if (savedDraft && !form.dataset.editing) { // Don't load draft when editing existing post
            try {
                const draft = JSON.parse(savedDraft);
                if (confirm('A draft was found. Would you like to restore it?')) {
                    title.value = draft.title || '';
                    content.value = draft.content || '';
                    if (form.querySelector('#author')) {
                        form.querySelector('#author').value = draft.author || 'Anonymous';
                    }
                    if (form.querySelector('#tags')) {
                        form.querySelector('#tags').value = draft.tags || '';
                    }
                }
            } catch (e) {
                console.warn('Failed to parse saved draft:', e);
            }
        }
        
        // Clear draft on successful submit
        form.addEventListener('submit', function() {
            localStorage.removeItem('nadb_blog_draft');
        });
    });
}

// Search functionality
function initializeSearch() {
    const searchInput = document.querySelector('#search-input');
    if (!searchInput) return;
    
    let searchTimeout;
    
    searchInput.addEventListener('input', function() {
        clearTimeout(searchTimeout);
        const query = this.value.trim();
        
        if (query.length < 2) {
            clearSearchResults();
            return;
        }
        
        searchTimeout = setTimeout(() => {
            performSearch(query);
        }, 300);
    });
}

function performSearch(query) {
    // This would typically make an API call to search posts
    // For now, we'll just filter visible posts
    const posts = document.querySelectorAll('.post-card');
    let visibleCount = 0;
    
    posts.forEach(function(post) {
        const title = post.querySelector('.post-card-title a').textContent.toLowerCase();
        const content = post.querySelector('.post-card-content p').textContent.toLowerCase();
        const tags = Array.from(post.querySelectorAll('.tag')).map(tag => tag.textContent.toLowerCase());
        
        const matches = title.includes(query.toLowerCase()) || 
                       content.includes(query.toLowerCase()) ||
                       tags.some(tag => tag.includes(query.toLowerCase()));
        
        if (matches) {
            post.style.display = '';
            visibleCount++;
        } else {
            post.style.display = 'none';
        }
    });
    
    // Show search results count
    updateSearchResultsCount(visibleCount, query);
}

function clearSearchResults() {
    const posts = document.querySelectorAll('.post-card');
    posts.forEach(function(post) {
        post.style.display = '';
    });
    
    const resultsCount = document.querySelector('.search-results-count');
    if (resultsCount) {
        resultsCount.remove();
    }
}

function updateSearchResultsCount(count, query) {
    let resultsCount = document.querySelector('.search-results-count');
    
    if (!resultsCount) {
        resultsCount = document.createElement('div');
        resultsCount.className = 'search-results-count';
        resultsCount.style.cssText = `
            margin-bottom: 1rem;
            padding: 0.5rem 1rem;
            background: var(--light);
            border-radius: var(--border-radius);
            color: var(--gray-dark);
            font-size: 0.875rem;
        `;
        
        const postsGrid = document.querySelector('.posts-grid');
        if (postsGrid) {
            postsGrid.parentNode.insertBefore(resultsCount, postsGrid);
        }
    }
    
    resultsCount.textContent = `Found ${count} post${count !== 1 ? 's' : ''} matching "${query}"`;
}

// Keyboard shortcuts
document.addEventListener('keydown', function(e) {
    // Ctrl/Cmd + S to save (prevent default browser save)
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        const form = document.querySelector('.post-form');
        if (form) {
            e.preventDefault();
            form.submit();
        }
    }
    
    // Escape to cancel/go back
    if (e.key === 'Escape') {
        const cancelBtn = document.querySelector('.btn-outline');
        if (cancelBtn && cancelBtn.textContent.includes('Cancel')) {
            cancelBtn.click();
        }
    }
});

// Initialize additional features when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    initializeAutoSave();
    initializeSearch();
});

// Add CSS for copy button
const style = document.createElement('style');
style.textContent = `
    .copy-code-btn {
        position: absolute;
        top: 0.5rem;
        right: 0.5rem;
        background: var(--gray-dark);
        color: white;
        border: none;
        border-radius: 4px;
        padding: 0.25rem 0.5rem;
        font-size: 0.75rem;
        cursor: pointer;
        opacity: 0.7;
        transition: opacity 0.2s ease;
    }
    
    .copy-code-btn:hover {
        opacity: 1;
    }
    
    pre:hover .copy-code-btn {
        opacity: 1;
    }
`;
document.head.appendChild(style);