// Get CSRF token
const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

// File upload handler function
function handleFileUpload(fileInput, progressBar, progressText, pathField, type) {
    const file = fileInput.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);
    formData.append('type', type);

    // Add roll number from form
    const rollInput = document.querySelector('input[name="roll_number"]');
    if (rollInput && rollInput.value.trim()) {
        formData.append('roll', rollInput.value.trim().toUpperCase());
    }

    // Show progress container
    const progressContainer = progressBar.closest('.progress-container');
    progressContainer.style.display = 'flex';

    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/upload', true);
    xhr.setRequestHeader('X-CSRFToken', csrfToken);

    // Show upload progress
    xhr.upload.onprogress = function (e) {
        if (e.lengthComputable) {
            const percent = Math.round((e.loaded / e.total) * 100);
            progressBar.value = percent;
            progressText.textContent = `${percent}%`;
        }
    };

    // Handle upload complete
    xhr.onload = function () {
        if (xhr.status === 200) {
            const response = JSON.parse(xhr.responseText);
            pathField.value = response.path;

            // Show uploaded image preview
            const previewId = type === 'profile' ? 'profile-preview' : 'payment-preview';
            const preview = document.getElementById(previewId);
            if (preview && response.path) {
                // Create proper URL for preview
                preview.src = '/' + response.path.replace('static/', '');
                preview.style.display = 'block';
            }

            // Reveal and autofill transaction ID for payment uploads
            if (type === 'payment' && response.trans_id) {
                const transInput = document.querySelector('input[name="trans_id"]');
                const transGroup = document.getElementById('trans-id-group');

                if (transInput && transGroup) {
                    transInput.value = response.trans_id;
                    transGroup.style.display = 'block';
                    transGroup.classList.add('visible');
                }
            }

            progressText.textContent = 'Upload complete!';
            progressText.style.color = 'green';
        } else {
            progressText.textContent = 'Upload failed!';
            progressText.style.color = 'red';
            console.error("Upload error:", xhr.responseText);
        }
    };

    // Handle network error
    xhr.onerror = function () {
        progressText.textContent = 'Upload error!';
        progressText.style.color = 'red';
        console.error("XHR failed:", xhr.statusText);
    };

    xhr.send(formData);
}

// Initialize event listeners when DOM is loaded
document.addEventListener('DOMContentLoaded', function () {
    // Profile upload
    const profileUpload = document.getElementById('profile-upload');
    const profileProgress = document.getElementById('profile-progress');
    const profileProgressText = document.getElementById('profile-progress-text');
    const profilePath = document.getElementById('profile_path');

    profileUpload.addEventListener('change', function () {
        handleFileUpload(this, profileProgress, profileProgressText, profilePath, 'profile');
    });

    // Payment upload
    const paymentUpload = document.getElementById('payment-upload');
    const paymentProgress = document.getElementById('payment-progress');
    const paymentProgressText = document.getElementById('payment-progress-text');
    const paymentPath = document.getElementById('payment_path');

    paymentUpload.addEventListener('change', function () {
        handleFileUpload(this, paymentProgress, paymentProgressText, paymentPath, 'payment');
    });

    // Update file labels when files are selected
    profileUpload.addEventListener('change', function () {
        const label = document.querySelector('label[for="profile-upload"]');
        if (this.files.length > 0) {
            label.textContent = this.files[0].name;
            label.style.color = '#4CAF50';
        }
    });

    paymentUpload.addEventListener('change', function () {
        const label = document.querySelector('label[for="payment-upload"]');
        if (this.files.length > 0) {
            label.textContent = this.files[0].name;
            label.style.color = '#4CAF50';
        }
    });
});