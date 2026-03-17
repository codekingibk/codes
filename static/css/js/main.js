// Global functions for the application

// Format date to YYYY-MM-DD
function formatDate(date = new Date()) {
    return date.toISOString().split('T')[0];
}

// Show loading spinner
function showLoading(container) {
    container.innerHTML = `
        <div class="text-center p-4">
            <div class="spinner-border text-primary" role="status"></div>
            <p class="mt-2">Loading...</p>
        </div>
    `;
}

// Show error message
function showError(container, message) {
    container.innerHTML = `<div class="alert alert-danger">${message}</div>`;
}

// Show success message
function showSuccess(message) {
    const alert = document.createElement('div');
    alert.className = 'alert alert-success alert-dismissible fade show';
    alert.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    
    const container = document.querySelector('main.container-xl') || document.body;
    container.insertBefore(alert, container.firstChild);
    
    setTimeout(() => {
        alert.remove();
    }, 5000);
}

// Copy to clipboard
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        showSuccess('Copied to clipboard!');
    }).catch(err => {
        console.error('Failed to copy:', err);
        alert('Failed to copy to clipboard');
    });
}

// Check for new notifications
let notificationCheckInterval = null;

function startNotificationCheck() {
    if (notificationCheckInterval) {
        clearInterval(notificationCheckInterval);
    }
    
    notificationCheckInterval = setInterval(checkNotifications, 30000); // Check every 30 seconds
}

function stopNotificationCheck() {
    if (notificationCheckInterval) {
        clearInterval(notificationCheckInterval);
        notificationCheckInterval = null;
    }
}

function checkNotifications() {
    fetch('/api/user/notifications')
        .then(response => response.json())
        .then(notifications => {
            if (notifications.length > 0) {
                updateNotificationBadge(notifications.length);
                showNotificationAlert(notifications);
            }
        })
        .catch(err => console.error('Error checking notifications:', err));
}

function updateNotificationBadge(count) {
    const badge = document.querySelector('.notification-badge');
    if (badge) {
        badge.textContent = count;
        badge.style.display = count > 0 ? 'inline' : 'none';
    }
}

function showNotificationAlert(notifications) {
    notifications.forEach(notif => {
        // Create toast notification
        const toast = document.createElement('div');
        toast.className = 'toast align-items-center text-white bg-primary border-0 position-fixed bottom-0 end-0 m-3';
        toast.setAttribute('role', 'alert');
        toast.setAttribute('aria-live', 'assertive');
        toast.setAttribute('aria-atomic', 'true');
        toast.innerHTML = `
            <div class="d-flex">
                <div class="toast-body">
                    <strong>${notif.title}</strong><br>
                    ${notif.message}
                </div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        `;
        
        document.body.appendChild(toast);
        const bsToast = new bootstrap.Toast(toast, { delay: 5000 });
        bsToast.show();

        if ('Notification' in window && Notification.permission === 'granted') {
            new Notification(notif.title || 'Codes', {
                body: notif.message || '',
                icon: '/static/favicon.png'
            });
        }
        
        // Mark as read when shown
        setTimeout(() => {
            fetch(`/api/user/mark-notification-read/${notif.id}`, { method: 'POST' });
        }, 1000);
    });
}

// Initialize tooltips
document.addEventListener('DOMContentLoaded', function() {
    // Initialize Bootstrap tooltips
    const tooltips = document.querySelectorAll('[data-bs-toggle="tooltip"]');
    tooltips.forEach(tooltip => {
        new bootstrap.Tooltip(tooltip);
    });
    
    // Start notification check for authenticated users
    if (document.body.getAttribute('data-authenticated') === 'true') {
        startNotificationCheck();
        checkNotifications();
    }
});

// Cleanup on page unload
window.addEventListener('beforeunload', function() {
    stopNotificationCheck();
});