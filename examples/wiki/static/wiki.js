// Wiki System - Interactive JavaScript
class WikiSystem {
    constructor() {
        this.init();
    }

    init() {
        this.setupEventListeners();
        this.setupMarkdownPreview();
        this.setupAutoSave();
        this.setupKeyboardShortcuts();
        this.highlightCode();
        this.updateStats();
    }

    setupEventListeners() {
        // Form submission
        const pageForm = document.getElementById('pageForm');
        if (pageForm) {
            pageForm.addEventListener('submit', (e) => this.handleFormSubmit(e));
        }

        // Tab switching
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', (e) => this.switchTab(e));
        });

        // Auto-generate slug from title
        const titleInput = document.getElementById('title');
        const slugInput = document.getElementById('slug');
        if (titleInput && slugInput && !slugInput.value) {
            titleInput.addEventListener('input', (e) => {
                const slug = this.generateSlug(e.target.value);
                slugInput.value = slug;
            });
        }

        // Search form enhancement
        const searchForm = document.querySelector('.search-form');
        if (searchForm) {
            const searchInput = searchForm.querySelector('.search-input');
            searchInput.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') {
                    searchInput.blur();
                }
            });
        }
    }

    setupMarkdownPreview() {
        const contentTextarea = document.getElementById('content');
        const previewBtn = document.querySelector('[data-tab="preview"]');
        
        if (contentTextarea && previewBtn) {
            previewBtn.addEventListener('click', () => {
                this.updatePreview();
            });

            // Auto-update preview when switching to preview tab
            contentTextarea.addEventListener('input', () => {
                if (document.querySelector('[data-tab="preview"]').classList.contains('active')) {
                    this.debounce(() => this.updatePreview(), 500)();
                }
            });
        }
    }

    setupAutoSave() {
        const contentTextarea = document.getElementById('content');
        if (contentTextarea) {
            // Auto-save draft to localStorage
            const autoSave = this.debounce(() => {
                const formData = this.getFormData();
                if (formData.content.trim()) {
                    localStorage.setItem('wiki_draft', JSON.stringify({
                        ...formData,
                        timestamp: new Date().toISOString()
                    }));
                    this.showToast('Rascunho salvo automaticamente', 'success');
                }
            }, 2000);

            contentTextarea.addEventListener('input', autoSave);

            // Load draft on page load
            this.loadDraft();
        }
    }

    setupKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            // Ctrl+S to save
            if (e.ctrlKey && e.key === 's') {
                e.preventDefault();
                const form = document.getElementById('pageForm');
                if (form) {
                    form.dispatchEvent(new Event('submit'));
                }
            }

            // Escape to cancel/close
            if (e.key === 'Escape') {
                const activeModal = document.querySelector('.modal.active');
                if (activeModal) {
                    this.closeModal(activeModal);
                }
            }

            // Ctrl+/ to focus search
            if (e.ctrlKey && e.key === '/') {
                e.preventDefault();
                const searchInput = document.querySelector('.search-input');
                if (searchInput) {
                    searchInput.focus();
                    searchInput.select();
                }
            }
        });
    }

    async handleFormSubmit(e) {
        e.preventDefault();
        
        const formData = this.getFormData();
        if (!this.validateForm(formData)) {
            return;
        }

        this.showLoading(true);

        try {
            const response = await fetch('/api/save', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(formData)
            });

            const result = await response.json();

            if (response.ok) {
                this.showToast('Página salva com sucesso!', 'success');
                
                // Clear draft
                localStorage.removeItem('wiki_draft');
                
                // Redirect to page
                setTimeout(() => {
                    window.location.href = `/page/${result.page.slug}`;
                }, 1000);
            } else {
                this.showToast(result.error || 'Erro ao salvar página', 'error');
            }
        } catch (error) {
            console.error('Error saving page:', error);
            this.showToast('Erro de conexão. Tente novamente.', 'error');
        } finally {
            this.showLoading(false);
        }
    }

    getFormData() {
        return {
            slug: document.getElementById('slug')?.value.trim() || '',
            title: document.getElementById('title')?.value.trim() || '',
            content: document.getElementById('content')?.value.trim() || '',
            tags: document.getElementById('tags')?.value.trim() || ''
        };
    }

    validateForm(data) {
        const errors = [];

        if (!data.slug) {
            errors.push('Slug é obrigatório');
        } else if (!/^[a-zA-Z0-9_-]+$/.test(data.slug)) {
            errors.push('Slug deve conter apenas letras, números, _ e -');
        }

        if (!data.title) {
            errors.push('Título é obrigatório');
        }

        if (!data.content) {
            errors.push('Conteúdo é obrigatório');
        }

        if (errors.length > 0) {
            this.showToast(errors.join('<br>'), 'error');
            return false;
        }

        return true;
    }

    switchTab(e) {
        const tabBtn = e.target.closest('.tab-btn');
        const tabName = tabBtn.dataset.tab;

        // Update tab buttons
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.classList.remove('active');
        });
        tabBtn.classList.add('active');

        // Update tab content
        document.querySelectorAll('.tab-content').forEach(content => {
            content.classList.remove('active');
        });
        document.getElementById(`${tabName}-tab`).classList.add('active');

        // Update preview if switching to preview tab
        if (tabName === 'preview') {
            this.updatePreview();
        }
    }

    async updatePreview() {
        const content = document.getElementById('content')?.value || '';
        const previewContent = document.getElementById('preview-content');
        
        if (!previewContent) return;

        if (!content.trim()) {
            previewContent.innerHTML = '<p><em>Preview aparecerá aqui...</em></p>';
            return;
        }

        try {
            const response = await fetch('/api/preview', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ content })
            });

            const result = await response.json();

            if (response.ok) {
                previewContent.innerHTML = result.html;
                this.highlightCode(previewContent);
            } else {
                previewContent.innerHTML = `<p class="error">Erro no preview: ${result.error}</p>`;
            }
        } catch (error) {
            console.error('Error updating preview:', error);
            previewContent.innerHTML = '<p class="error">Erro de conexão no preview</p>';
        }
    }

    generateSlug(title) {
        return title
            .toLowerCase()
            .normalize('NFD')
            .replace(/[\u0300-\u036f]/g, '') // Remove accents
            .replace(/[^a-z0-9\s-]/g, '') // Remove special chars
            .replace(/\s+/g, '-') // Replace spaces with hyphens
            .replace(/-+/g, '-') // Replace multiple hyphens
            .replace(/^-|-$/g, ''); // Remove leading/trailing hyphens
    }

    loadDraft() {
        const draft = localStorage.getItem('wiki_draft');
        if (!draft) return;

        try {
            const draftData = JSON.parse(draft);
            const draftAge = Date.now() - new Date(draftData.timestamp).getTime();
            
            // Only load drafts less than 24 hours old
            if (draftAge > 24 * 60 * 60 * 1000) {
                localStorage.removeItem('wiki_draft');
                return;
            }

            // Check if current form is empty
            const currentData = this.getFormData();
            const isEmpty = !currentData.title && !currentData.content;

            if (isEmpty) {
                if (confirm('Rascunho encontrado. Deseja carregá-lo?')) {
                    this.fillForm(draftData);
                    this.showToast('Rascunho carregado', 'success');
                }
            }
        } catch (error) {
            console.error('Error loading draft:', error);
            localStorage.removeItem('wiki_draft');
        }
    }

    fillForm(data) {
        const fields = ['slug', 'title', 'content', 'tags'];
        fields.forEach(field => {
            const element = document.getElementById(field);
            if (element && data[field]) {
                element.value = data[field];
            }
        });
    }

    highlightCode(container = document) {
        if (typeof hljs !== 'undefined') {
            container.querySelectorAll('pre code').forEach((block) => {
                hljs.highlightElement(block);
            });
        }
    }

    async updateStats() {
        try {
            const response = await fetch('/api/stats');
            const stats = await response.json();
            
            // Update stats in sidebar if present
            const statNumbers = document.querySelectorAll('.stat-number');
            if (statNumbers.length >= 2) {
                statNumbers[0].textContent = stats.total_pages || 0;
                statNumbers[1].textContent = stats.total_views || 0;
            }
        } catch (error) {
            console.error('Error updating stats:', error);
        }
    }

    showToast(message, type = 'info') {
        const container = document.getElementById('toast-container');
        if (!container) return;

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.innerHTML = `
            <div class="toast-content">
                <div class="toast-message">${message}</div>
                <button class="toast-close" onclick="this.parentElement.parentElement.remove()">
                    <i class="fas fa-times"></i>
                </button>
            </div>
        `;

        container.appendChild(toast);

        // Auto-remove after 5 seconds
        setTimeout(() => {
            if (toast.parentElement) {
                toast.remove();
            }
        }, 5000);
    }

    showLoading(show) {
        const overlay = document.getElementById('loading-overlay');
        if (overlay) {
            overlay.classList.toggle('active', show);
        }
    }

    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }

    // Utility methods for future enhancements
    formatDate(dateString) {
        const date = new Date(dateString);
        return date.toLocaleDateString('pt-BR', {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    }

    truncateText(text, maxLength = 100) {
        if (text.length <= maxLength) return text;
        return text.substr(0, maxLength) + '...';
    }

    copyToClipboard(text) {
        if (navigator.clipboard) {
            navigator.clipboard.writeText(text).then(() => {
                this.showToast('Copiado para a área de transferência!', 'success');
            });
        } else {
            // Fallback for older browsers
            const textArea = document.createElement('textarea');
            textArea.value = text;
            document.body.appendChild(textArea);
            textArea.select();
            document.execCommand('copy');
            document.body.removeChild(textArea);
            this.showToast('Copiado para a área de transferência!', 'success');
        }
    }
}

// Enhanced Markdown filter for Jinja2 (if needed)
if (typeof marked !== 'undefined') {
    // Configure marked for better rendering
    marked.setOptions({
        highlight: function(code, lang) {
            if (typeof hljs !== 'undefined' && lang && hljs.getLanguage(lang)) {
                try {
                    return hljs.highlight(code, { language: lang }).value;
                } catch (err) {}
            }
            return code;
        },
        breaks: true,
        gfm: true
    });
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new WikiSystem();
});

// Add CSS for toast close button
const style = document.createElement('style');
style.textContent = `
    .toast-content {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 1rem;
    }
    
    .toast-message {
        flex: 1;
    }
    
    .toast-close {
        background: none;
        border: none;
        cursor: pointer;
        color: var(--text-secondary);
        padding: 0.25rem;
        border-radius: var(--radius-sm);
        transition: color 0.2s;
    }
    
    .toast-close:hover {
        color: var(--text-primary);
    }
    
    .error {
        color: var(--error-color);
    }
`;
document.head.appendChild(style);