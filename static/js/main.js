// Utility function to handle form submissions with AJAX
function handleFormSubmit(form, options = {}) {
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const submitButton = form.querySelector('button[type="submit"]');
        const originalText = submitButton.textContent;
        submitButton.disabled = true;
        submitButton.textContent = 'Processing...';

        try {
            const formData = new FormData(form);
            const response = await fetch(form.action, {
                method: form.method,
                body: formData,
                headers: {
                    'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
                }
            });

            const data = await response.json();

            if (response.ok) {
                if (options.onSuccess) {
                    options.onSuccess(data);
                }
            } else {
                throw new Error(data.message || 'Something went wrong');
            }
        } catch (error) {
            if (options.onError) {
                options.onError(error);
            } else {
                showNotification(error.message, 'error');
            }
        } finally {
            submitButton.disabled = false;
            submitButton.textContent = originalText;
        }
    });
}

// Utility function to show notifications
function showNotification(message, type = 'success') {
    const notification = document.createElement('div');
    notification.className = `fixed top-4 right-4 p-4 rounded-lg shadow-lg ${
        type === 'error' ? 'bg-red-500' : 'bg-green-500'
    } text-white z-50 transition-opacity duration-500`;
    notification.textContent = message;

    document.body.appendChild(notification);

    setTimeout(() => {
        notification.style.opacity = '0';
        setTimeout(() => notification.remove(), 500);
    }, 3000);
}

// Controller for handling the prompt form
class PromptController {
    constructor(formElement) {
        this.form = formElement;
        this.setupEventListeners();
    }

    setupEventListeners() {
        handleFormSubmit(this.form, {
            onSuccess: (data) => {
                showNotification('App generation started!');
                if (data.redirectUrl) {
                    window.location.href = data.redirectUrl;
                }
            },
            onError: (error) => {
                showNotification(error.message, 'error');
            }
        });
    }
}

// Initialize controllers when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    const promptForm = document.querySelector('form[action*="generate_app"]');
    if (promptForm) {
        new PromptController(promptForm);
    }
}); 