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

  // 2. Automated status polling & download button activation for job detail view
  const jobTracker = document.getElementById('job-status-tracker');
  if (jobTracker) {
    const jobId = jobTracker.getAttribute('data-job-id');
    const statusTextEl = document.getElementById('job-status-text');
    const statusBadgeEl = document.getElementById('job-status-badge');
    const downloadContainer = document.getElementById('job-download-container');
    const downloadLink = document.getElementById('job-download-link');
    const downloadOutputSize = document.getElementById('download-output-size');
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
          if (data.output_size_formatted && downloadOutputSize) {
            downloadOutputSize.textContent = data.output_size_formatted;
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
    }, 2000);
  }
});
