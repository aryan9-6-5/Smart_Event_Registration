// Get CSRF token
const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

// ─── Validation Rules ─────────────────────────────────────────────────────────
const VALIDATION_RULES = {
    name: {
        pattern: /^[a-zA-Z\s.'-]{2,100}$/,
        message: 'Name must be 2-100 characters (letters, spaces, dots, hyphens only).',
        required: true
    },
    email: {
        pattern: /^[^\s@]+@[^\s@]+\.[^\s@]+$/,
        message: 'Please enter a valid email address (e.g. name@example.com).',
        required: true
    },
    roll_number: {
        pattern: /^[a-zA-Z0-9]{2,20}$/,
        message: 'Roll number must be 2-20 alphanumeric characters.',
        required: true
    },
    dept_name: {
        pattern: /^.{1,100}$/,
        message: 'Department name is required (max 100 characters).',
        required: true
    },
    college_name: {
        pattern: /^.{1,100}$/,
        message: 'College name is required (max 100 characters).',
        required: true
    },
    phone: {
        pattern: /^\d{10}$/,
        message: 'Phone number must be exactly 10 digits. No spaces, dashes, or country codes.',
        required: true
    },
    trans_id: {
        pattern: /^[a-zA-Z0-9-]{5,50}$/,
        message: 'Transaction ID must be 5-50 alphanumeric characters.',
        required: true
    }
};

// Track upload states
const uploadState = {
    profile: false,
    payment: false
};

// ─── File Upload Handler ──────────────────────────────────────────────────────
function handleFileUpload(fileInput, progressBar, progressText, pathField, type) {
    const file = fileInput.files[0];
    if (!file) return;

    // Immediately clear path, reset upload state, and remove uploaded state styling
    pathField.value = '';
    uploadState[type] = false;

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

    const uploadCard = fileInput.closest('.upload-card');

    // Clear any previous error states and uploaded state
    if (uploadCard) {
        uploadCard.classList.remove('uploaded');
        uploadCard.classList.remove('upload-failed');
        const existingError = uploadCard.querySelector('.upload-error');
        if (existingError) existingError.remove();
    }

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
            uploadState[type] = true;

            if (uploadCard) {
                uploadCard.classList.add('uploaded');
                uploadCard.classList.remove('upload-failed');
            }

            // Show uploaded image preview
            const previewId = type === 'profile' ? 'profile-preview' : 'payment-preview';
            const preview = document.getElementById(previewId);
            if (preview) {
                preview.src = URL.createObjectURL(file);
                preview.style.display = 'block';
            }

            // Synchronize with Live Pass Preview
            if (type === 'profile') {
                const passPhoto = document.getElementById('preview-pass-photo');
                const passPhotoPlaceholder = document.getElementById('preview-pass-photo-placeholder');
                if (passPhoto && passPhotoPlaceholder) {
                    passPhoto.src = URL.createObjectURL(file);
                    passPhoto.style.display = 'block';
                    passPhotoPlaceholder.style.display = 'none';
                }
            }

            if (type === 'payment') {
                const transInput = document.getElementById('trans_id') || document.querySelector('input[name="trans_id"]');
                const transGroup = document.getElementById('trans-id-group');
                const lockIcon = document.getElementById('trans-lock-icon');

                if (transInput && transGroup) {
                    if (response.trans_id) {
                        transInput.value = response.trans_id;
                        transInput.readOnly = true;
                        transInput.classList.add('locked');
                        if (lockIcon) lockIcon.style.display = 'flex';
                    } else {
                        transInput.value = '';
                        transInput.readOnly = false;
                        transInput.classList.remove('locked');
                        if (lockIcon) lockIcon.style.display = 'none';
                    }
                    transGroup.style.display = 'block';
                    transGroup.classList.add('visible');
                }
            }

            progressText.textContent = 'Upload complete!';
            progressText.classList.add('upload-complete');
            progressText.style.color = 'white';
        } else {
            // ─── UPLOAD FAILED: Clear path and mark as failed ───────────
            pathField.value = '';
            uploadState[type] = false;
            progressText.textContent = 'Upload failed!';
            progressText.style.color = 'red';

            if (uploadCard) {
                uploadCard.classList.remove('uploaded');
                uploadCard.classList.add('upload-failed');
                // Show error message on the card
                let errEl = uploadCard.querySelector('.upload-error');
                if (!errEl) {
                    errEl = document.createElement('div');
                    errEl.className = 'upload-error';
                    uploadCard.appendChild(errEl);
                }
                errEl.textContent = 'Upload failed. Please try again.';
            }

            console.error("Upload error:", xhr.responseText);
        }
    };

    // Handle network error
    xhr.onerror = function () {
        // ─── NETWORK ERROR: Clear path and mark as failed ───────────
        pathField.value = '';
        uploadState[type] = false;
        progressText.textContent = 'Network error!';
        progressText.style.color = 'red';

        if (uploadCard) {
            uploadCard.classList.remove('uploaded');
            uploadCard.classList.add('upload-failed');
            let errEl = uploadCard.querySelector('.upload-error');
            if (!errEl) {
                errEl = document.createElement('div');
                errEl.className = 'upload-error';
                uploadCard.appendChild(errEl);
            }
            errEl.textContent = 'Network error. Check your connection.';
        }

        console.error("XHR failed:", xhr.statusText);
    };

    xhr.send(formData);
}

// ─── Client-Side Validation Helpers ───────────────────────────────────────────
function validateField(input) {
    const fieldName = input.name;
    const rule = VALIDATION_RULES[fieldName];
    if (!rule) return true;

    const value = input.value.trim();

    // Remove existing JS error
    const existingError = input.parentElement.querySelector('.js-field-error');
    if (existingError) existingError.remove();

    if (rule.required && !value) {
        setFieldState(input, 'invalid', `${fieldName.replace('_', ' ')} is required.`);
        return false;
    }

    if (value && !rule.pattern.test(value)) {
        setFieldState(input, 'invalid', rule.message);
        return false;
    }

    if (value) {
        setFieldState(input, 'valid');
    } else {
        setFieldState(input, 'neutral');
    }
    return true;
}

function setFieldState(input, state, message) {
    input.classList.remove('valid', 'invalid');

    // Remove existing JS error
    const existingError = input.parentElement.querySelector('.js-field-error');
    if (existingError) existingError.remove();

    if (state === 'valid') {
        input.classList.add('valid');
    } else if (state === 'invalid') {
        input.classList.add('invalid');
        if (message) {
            const errSpan = document.createElement('span');
            errSpan.className = 'js-field-error';
            errSpan.textContent = message;
            input.parentElement.appendChild(errSpan);
        }
    }
}

function validateAllFields() {
    let allValid = true;
    const fields = ['name', 'email', 'roll_number', 'dept_name', 'college_name', 'phone'];

    fields.forEach(fieldName => {
        const input = document.querySelector(`input[name="${fieldName}"]`);
        if (input && !validateField(input)) {
            allValid = false;
        }
    });

    return allValid;
}

// ─── Initialize Event Listeners ───────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {

    // 1. Initialize File Upload Listeners
    const profileUpload = document.getElementById('profile-upload');
    const profileProgress = document.getElementById('profile-progress');
    const profileProgressText = document.getElementById('profile-progress-text');
    const profilePath = document.getElementById('profile_path');

    if (profileUpload) {
        profileUpload.addEventListener('change', function () {
            handleFileUpload(this, profileProgress, profileProgressText, profilePath, 'profile');
            const label = document.querySelector('label[for="profile-upload"]');
            if (this.files.length > 0 && label) {
                label.textContent = this.files[0].name;
                label.style.color = 'white';
            }
        });
    }

    const paymentUpload = document.getElementById('payment-upload');
    const paymentProgress = document.getElementById('payment-progress');
    const paymentProgressText = document.getElementById('payment-progress-text');
    const paymentPath = document.getElementById('payment_path');

    if (paymentUpload) {
        paymentUpload.addEventListener('change', function () {
            handleFileUpload(this, paymentProgress, paymentProgressText, paymentPath, 'payment');
            const label = document.querySelector('label[for="payment-upload"]');
            if (this.files.length > 0 && label) {
                label.textContent = this.files[0].name;
                label.style.color = 'white';
            }
        });
    }

    // 2. Populate Mock Ticket Pass Preview with EVENT_CONFIG Globals
    if (typeof EVENT_CONFIG !== 'undefined') {
        const passTitle = document.getElementById('preview-pass-title');
        const passSubtitle = document.getElementById('preview-pass-subtitle');
        const passDate = document.getElementById('preview-pass-date');

        if (passTitle && EVENT_CONFIG.title) passTitle.textContent = EVENT_CONFIG.title.toUpperCase();
        if (passSubtitle && EVENT_CONFIG.subtitle) passSubtitle.textContent = EVENT_CONFIG.subtitle.toUpperCase();
        if (passDate && EVENT_CONFIG.date) passDate.textContent = EVENT_CONFIG.date.toUpperCase();
    }

    // 3. Setup Live Text Update Pass-Through
    const nameInput = document.querySelector('input[name="name"]');
    const rollInput = document.querySelector('input[name="roll_number"]');
    const deptInput = document.querySelector('input[name="dept_name"]');
    const collegeInput = document.querySelector('input[name="college_name"]');
    const phoneInput = document.querySelector('input[name="phone"]');

    const previewName = document.getElementById('preview-pass-name');
    const previewRoll = document.getElementById('preview-pass-roll');
    const previewDept = document.getElementById('preview-pass-dept');
    const previewCollege = document.getElementById('preview-pass-college');
    const previewPhone = document.getElementById('preview-pass-phone');
    const previewTicketId = document.getElementById('preview-pass-ticket-id');

    function bindLivePreview(inputEl, previewEl, fallbackText) {
        if (inputEl && previewEl) {
            const updateValue = () => {
                const val = inputEl.value.trim();
                previewEl.textContent = val ? val : fallbackText;
            };
            inputEl.addEventListener('input', updateValue);
            updateValue();
        }
    }

    bindLivePreview(nameInput, previewName, '-');
    bindLivePreview(rollInput, previewRoll, '-');
    bindLivePreview(deptInput, previewDept, '-');
    bindLivePreview(collegeInput, previewCollege, '-');
    bindLivePreview(phoneInput, previewPhone, '-');

    if (rollInput && previewTicketId) {
        const updateTicketId = () => {
            const val = rollInput.value.trim().toUpperCase();
            const prefix = (typeof EVENT_CONFIG !== 'undefined' && EVENT_CONFIG.ticketPrefix) ? EVENT_CONFIG.ticketPrefix : 'TECH24-';
            previewTicketId.textContent = val ? `${prefix}${val}` : '-';
        };
        rollInput.addEventListener('input', updateTicketId);
        updateTicketId();
    }

    // 4. Real-Time Blur Validation for All Fields
    const validatableFields = ['name', 'email', 'roll_number', 'dept_name', 'college_name', 'phone'];
    validatableFields.forEach(fieldName => {
        const input = document.querySelector(`input[name="${fieldName}"]`);
        if (input) {
            input.addEventListener('blur', () => validateField(input));
            // Also validate on input for real-time feedback after first blur
            input.addEventListener('input', () => {
                if (input.classList.contains('invalid') || input.classList.contains('valid')) {
                    validateField(input);
                }
            });
        }
    });

    // 5. Phone Character Counter
    const phoneCounter = document.getElementById('phone-counter');
    if (phoneInput && phoneCounter) {
        phoneInput.addEventListener('input', () => {
            const len = phoneInput.value.replace(/\D/g, '').length;
            phoneCounter.textContent = `${len}/10`;
            phoneCounter.classList.remove('valid', 'invalid');
            if (len === 10) {
                phoneCounter.classList.add('valid');
            } else if (len > 10) {
                phoneCounter.classList.add('invalid');
            }
        });
    }

    // 6. Pre-Submit Guard: Block form submission if validation fails or uploads missing
    const registrationForm = document.querySelector('.registration-form');
    if (registrationForm) {
        registrationForm.addEventListener('submit', function (e) {
            // Remove any existing validation banner
            const existingBanner = registrationForm.querySelector('.form-validation-banner');
            if (existingBanner) existingBanner.remove();

            const errors = [];

            // Validate all text fields
            if (!validateAllFields()) {
                errors.push('Please fix the highlighted field errors above.');
            }

            // Check profile upload
            const profilePathValue = document.getElementById('profile_path')?.value;
            if (!profilePathValue || !profilePathValue.trim()) {
                errors.push('Profile photo is required. Please upload your photo.');
                const profileCard = document.querySelector('#profile-upload')?.closest('.upload-card');
                if (profileCard) {
                    profileCard.classList.add('upload-failed');
                }
            }

            // Check payment upload
            const paymentPathValue = document.getElementById('payment_path')?.value;
            if (!paymentPathValue || !paymentPathValue.trim()) {
                errors.push('Payment proof is required. Please upload your payment screenshot.');
                const paymentCard = document.querySelector('#payment-upload')?.closest('.upload-card');
                if (paymentCard) {
                    paymentCard.classList.add('upload-failed');
                }
            }

            if (errors.length > 0) {
                e.preventDefault();

                const banner = document.createElement('div');
                banner.className = 'form-validation-banner';
                banner.innerHTML = `
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
                    </svg>
                    <span>${errors[0]}</span>
                `;

                // Insert banner before the form grid
                const formGrid = registrationForm.querySelector('.form-grid');
                if (formGrid) {
                    registrationForm.insertBefore(banner, formGrid);
                } else {
                    registrationForm.prepend(banner);
                }

                // Scroll to the banner
                banner.scrollIntoView({ behavior: 'smooth', block: 'center' });
                return;
            }

            // Add loading state to submit button
            const submitBtn = registrationForm.querySelector('.submit-btn');
            if (submitBtn) {
                submitBtn.classList.add('loading');
            }
        });
    }

    // 7. QR Code Modal Overlay logic
    const qrModal = document.getElementById('qr-modal');
    const qrZoomBtn = document.querySelector('.qr-zoom-btn');
    const modalCloseBtn = document.getElementById('modal-close-btn');

    if (qrZoomBtn && qrModal && modalCloseBtn) {
        qrZoomBtn.addEventListener('click', function (e) {
            e.preventDefault();
            qrModal.style.display = 'flex';
            // Trigger reflow for CSS transition
            setTimeout(() => {
                qrModal.classList.add('active');
            }, 10);
        });

        const closeModal = function () {
            qrModal.classList.remove('active');
            setTimeout(() => {
                qrModal.style.display = 'none';
            }, 300);
        };

        modalCloseBtn.addEventListener('click', closeModal);

        qrModal.addEventListener('click', function (e) {
            // Close if clicked on the overlay background, not the content wrapper
            if (e.target === qrModal) {
                closeModal();
            }
        });

        // Close on ESC key press
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && qrModal.classList.contains('active')) {
                closeModal();
            }
        });
    }
});