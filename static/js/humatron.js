// Humatron Minimal Vanilla JavaScript Helper
document.addEventListener('DOMContentLoaded', function () {
  // 1. Dynamic toggle for Job Title 'Other' in registration & profile
  const jobTitleSelect = document.getElementById('id_job_title');
  const jobTitleOtherInput = document.getElementById('id_job_title_other');
  if (jobTitleSelect && jobTitleOtherInput) {
    const parentGroup = jobTitleOtherInput.closest('.form-group');
    function updateOtherVisibility() {
      if (jobTitleSelect.value === 'Other') {
        if (parentGroup) parentGroup.style.display = 'block';
      } else {
        if (parentGroup) parentGroup.style.display = 'none';
      }
    }
    jobTitleSelect.addEventListener('change', updateOtherVisibility);
    updateOtherVisibility();
  }

  // 2. Interactive PDF Upload & File Selection Helper
  const uploadDropzone = document.getElementById('upload-dropzone');
  const fileInput = document.getElementById('pdf-file-input');
  const browseBtn = document.getElementById('browse-pdf-btn');
  const changeBtn = document.getElementById('change-file-btn');
  const selectedFileCard = document.getElementById('selected-file-card');
  const selectedFileName = document.getElementById('selected-file-name');
  const selectedFileSize = document.getElementById('selected-file-size');
  const uploadForm = document.getElementById('pdf-upload-form');
  const uploadSubmitBtn = document.getElementById('upload-submit-btn');

  function formatBytes(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  }

  function handleFileSelected(file) {
    if (!file) return;
    if (selectedFileName) selectedFileName.textContent = file.name;
    if (selectedFileSize) selectedFileSize.textContent = formatBytes(file.size);
    if (selectedFileCard) selectedFileCard.style.display = 'flex';
    if (uploadDropzone) {
      uploadDropzone.style.borderColor = '#15803d';
      uploadDropzone.style.backgroundColor = '#f0fdf4';
    }
  }

  if (fileInput) {
    fileInput.addEventListener('change', function () {
      if (this.files && this.files.length > 0) {
        handleFileSelected(this.files[0]);
      }
    });

    if (browseBtn) {
      browseBtn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        fileInput.click();
      });
    }

    if (changeBtn) {
      changeBtn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        fileInput.click();
      });
    }

    if (uploadDropzone) {
      uploadDropzone.addEventListener('click', function () {
        fileInput.click();
      });

      ['dragenter', 'dragover'].forEach(eventName => {
        uploadDropzone.addEventListener(eventName, function (e) {
          e.preventDefault();
          e.stopPropagation();
          uploadDropzone.classList.add('dragover');
        }, false);
      });

      ['dragleave', 'drop'].forEach(eventName => {
        uploadDropzone.addEventListener(eventName, function (e) {
          e.preventDefault();
          e.stopPropagation();
          uploadDropzone.classList.remove('dragover');
        }, false);
      });

      uploadDropzone.addEventListener('drop', function (e) {
        if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
          const droppedFile = e.dataTransfer.files[0];
          if (droppedFile.type === 'application/pdf' || droppedFile.name.toLowerCase().endsWith('.pdf')) {
            fileInput.files = e.dataTransfer.files;
            handleFileSelected(droppedFile);
          } else {
            alert('Please select a valid PDF file (.pdf)');
          }
        }
      });
    }

    if (uploadForm && uploadSubmitBtn) {
      uploadForm.addEventListener('submit', function () {
        if (fileInput.files && fileInput.files.length > 0) {
          uploadSubmitBtn.disabled = true;
          uploadSubmitBtn.innerHTML = '⏳ Uploading & Processing... Please wait';
          uploadSubmitBtn.style.opacity = '0.85';
          uploadSubmitBtn.style.cursor = 'not-allowed';
        }
      });
    }
  }

  // 3. Automated status polling & download activation for job detail view
  const jobTracker = document.getElementById('job-status-tracker');
  if (jobTracker) {
    const jobId = jobTracker.getAttribute('data-job-id');
    const statusTextEl = document.getElementById('job-status-text');
    const statusBadgeEl = document.getElementById('job-status-badge');
    const downloadContainer = document.getElementById('job-download-container');
    const downloadLink = document.getElementById('job-download-link');
    const downloadOutputSize = document.getElementById('download-output-size');
    const jobOutputSize = document.getElementById('job-output-size');
    const jobPageCount = document.getElementById('job-page-count');
    const processingNotice = document.getElementById('job-processing-notice');
    const errorContainer = document.getElementById('job-error-container');
    const errorText = document.getElementById('job-error-text');

    let pollInterval = setInterval(function () {
      fetch(`/pdf/jobs/${jobId}/?format=json`, {
        headers: {
          'X-Requested-With': 'XMLHttpRequest'
        }
      })
      .then(response => response.json())
      .then(data => {
        if (data.status) {
          if (statusTextEl) statusTextEl.textContent = data.status;
          if (data.page_count && jobPageCount) jobPageCount.textContent = data.page_count;
          if (data.output_size_formatted) {
            if (jobOutputSize) jobOutputSize.textContent = data.output_size_formatted;
            if (downloadOutputSize) downloadOutputSize.textContent = data.output_size_formatted;
          }

          if (data.status === 'COMPLETED') {
            clearInterval(pollInterval);
            if (statusBadgeEl) {
              statusBadgeEl.className = 'badge badge-completed';
              statusBadgeEl.textContent = 'Completed';
            }
            if (processingNotice) processingNotice.style.display = 'none';
            if (downloadContainer && data.download_url) {
              downloadContainer.style.display = 'block';
              if (downloadLink) downloadLink.href = data.download_url;
            }
          } else if (data.status === 'FAILED') {
            clearInterval(pollInterval);
            if (statusBadgeEl) {
              statusBadgeEl.className = 'badge badge-failed';
              statusBadgeEl.textContent = 'Failed';
            }
            if (processingNotice) processingNotice.style.display = 'none';
            if (errorContainer) {
              errorContainer.style.display = 'block';
              if (errorText) errorText.textContent = data.error_message || 'An error occurred during document conversion.';
            }
          } else if (data.status === 'PROCESSING') {
            if (statusBadgeEl) {
              statusBadgeEl.className = 'badge badge-processing';
              statusBadgeEl.textContent = 'Processing...';
            }
          }
        }
      })
      .catch(err => {
        console.error('Job polling error:', err);
      });
    }, 2500);
  }
});
