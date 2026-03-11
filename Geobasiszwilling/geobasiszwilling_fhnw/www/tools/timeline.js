/**
 * @file tools/timeline.js
 * Timeline controls and custom date/time picker functionality
 */

function initTimelineControls(viewer) {
  // Timeline Toggle Button
  const timelineContainer = document.querySelector('.cesium-viewer-timelineContainer');
  const timelineToggleBtn = document.getElementById('timelineToggleBtn');
  const timelineControls = document.getElementById('timelineControls');
  const timelineControlsToggle = document.getElementById('timelineControlsToggle');
  const currentDateTime = document.getElementById('currentDateTime');
  const coordPanel = document.getElementById('coordPanel');
  let timelineVisible = false;
  let controlsVisible = false;
  
  // Update current date/time display
  function updateCurrentDateTime() {
    const now = viewer.clock.currentTime;
    const date = Cesium.JulianDate.toGregorianDate(now);
    
    // Convert UTC to local time
    const utcDate = new Date(Date.UTC(date.year, date.month - 1, date.day, date.hour, date.minute, date.second));
    const localDate = new Date(utcDate.getTime());
    
    const day = String(localDate.getDate()).padStart(2, '0');
    const month = String(localDate.getMonth() + 1).padStart(2, '0');
    const year = localDate.getFullYear();
    const hours = String(localDate.getHours()).padStart(2, '0');
    const minutes = String(localDate.getMinutes()).padStart(2, '0');
    
    const dateStr = `${day}.${month}.${year}`;
    const timeStr = `${hours}:${minutes}`;
    
    if (currentDateTime) {
      currentDateTime.textContent = `${dateStr} ${timeStr}`;
    }
  }
  
  // Update every second when timeline is visible
  let updateInterval = null;
  
  // Hide timeline by default
  if (timelineContainer) {
    timelineContainer.style.display = 'none';
  }
  timelineToggleBtn.style.opacity = '0.5';
  
  timelineToggleBtn.addEventListener('click', () => {
    timelineVisible = !timelineVisible;
    if (timelineContainer) {
      timelineContainer.style.display = timelineVisible ? 'block' : 'none';
    }
    if (timelineControls) {
      timelineControls.style.display = timelineVisible ? 'flex' : 'none';
      controlsVisible = timelineVisible;
    }
    // Toggle Button bleibt versteckt beim Öffnen der Timeline
    if (timelineControlsToggle) {
      timelineControlsToggle.style.display = 'none';
    }
    if (coordPanel) {
      coordPanel.style.display = timelineVisible ? 'none' : 'block';
    }
    timelineToggleBtn.style.opacity = timelineVisible ? '1' : '0.5';
    
    // Start/stop updating current date/time
    if (timelineVisible) {
      updateCurrentDateTime();
      updateInterval = setInterval(updateCurrentDateTime, 100);
      
      setTimeout(() => {
        const dayButton = document.querySelector('.timeline-scale-btn[data-scale="day"]');
        if (dayButton) {
          dayButton.click();
        }
      }, 100);
    } else {
      if (updateInterval) {
        clearInterval(updateInterval);
        updateInterval = null;
      }
    }
  });

  // Timeline Controls Toggle Button (Uhr-Icon)
  if (timelineControlsToggle) {
    timelineControlsToggle.addEventListener('click', () => {
      controlsVisible = true;
      if (timelineControls) {
        timelineControls.style.display = 'flex';
      }
      timelineControlsToggle.style.display = 'none';
    });
  }

  // Close Timeline Controls Button
  const closeTimelineControls = document.getElementById('closeTimelineControls');
  if (closeTimelineControls) {
    closeTimelineControls.addEventListener('click', () => {
      controlsVisible = false;
      if (timelineControls) {
        timelineControls.style.display = 'none';
      }
      if (timelineControlsToggle) {
        timelineControlsToggle.style.display = 'flex';
      }
    });
  }



  // Timeline Scale Buttons
  const scaleButtons = document.querySelectorAll('.timeline-scale-btn');
  scaleButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      scaleButtons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      const scale = btn.getAttribute('data-scale');
      const currentTime = viewer.clock.currentTime;
      let startTime, endTime;

      switch(scale) {
        case 'day': {
          const currentDate = Cesium.JulianDate.toGregorianDate(currentTime);
          startTime = Cesium.JulianDate.fromDate(new Date(currentDate.year, currentDate.month - 1, currentDate.day, 0, 0, 0));
          endTime = Cesium.JulianDate.fromDate(new Date(currentDate.year, currentDate.month - 1, currentDate.day, 23, 59, 59));
          break;
        }
        case 'year': {
          const currentYear = Cesium.JulianDate.toGregorianDate(currentTime);
          startTime = Cesium.JulianDate.fromDate(new Date(currentYear.year, 0, 1, 0, 0, 0));
          endTime = Cesium.JulianDate.fromDate(new Date(currentYear.year, 11, 31, 23, 59, 59));
          break;
        }
        case 'decade': {
          const currentDecade = Cesium.JulianDate.toGregorianDate(currentTime);
          startTime = Cesium.JulianDate.fromDate(new Date(currentDecade.year - 5, 0, 1, 0, 0, 0));
          endTime = Cesium.JulianDate.fromDate(new Date(currentDecade.year + 5, 11, 31, 23, 59, 59));
          break;
        }
        case '50years': {
          const current50 = Cesium.JulianDate.toGregorianDate(currentTime);
          startTime = Cesium.JulianDate.fromDate(new Date(current50.year - 25, 0, 1, 0, 0, 0));
          endTime = Cesium.JulianDate.fromDate(new Date(current50.year + 25, 11, 31, 23, 59, 59));
          break;
        }
      }

      // Prüfe, ob startTime und endTime gültige JulianDate-Objekte sind
      function isValidJD(jd) {
        return jd && typeof jd.dayNumber !== 'undefined';
      }
      if (isValidJD(startTime) && isValidJD(endTime)) {
        viewer.timeline.zoomTo(startTime, endTime);
        setTimeout(() => {
          if (viewer.timeline) {
            viewer.timeline.resize();
          }
        }, 50);
      } else {
        console.error('Timeline-Fehler: Ungültige JulianDate-Objekte', {startTime, endTime});
      }
    });
  });

  // Set default scale to 'day'
  if (scaleButtons.length > 0) {
    scaleButtons[0].classList.add('active');
  }

  // Custom Date Picker
  const dateInput = document.getElementById('customDateInput');
  const calendarPopup = document.querySelector('.calendar-popup');
  const calendarGrid = document.querySelector('.calendar-grid');
  const monthYearDisplay = document.getElementById('monthYearDisplay');
  const prevMonthBtn = document.getElementById('prevMonth');
  const nextMonthBtn = document.getElementById('nextMonth');
  
  let currentCalendarDate = new Date();
  let selectedDate = null;
  
  // Toggle calendar popup
  if (dateInput) {
    dateInput.addEventListener('click', (e) => {
      e.stopPropagation();
      if (calendarPopup) {
        calendarPopup.style.display = calendarPopup.style.display === 'block' ? 'none' : 'block';
        if (calendarPopup.style.display === 'block') {
          renderCalendar(currentCalendarDate);
        }
      }
    });
  }
  
  // Navigate months
  if (prevMonthBtn) {
    prevMonthBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      currentCalendarDate.setMonth(currentCalendarDate.getMonth() - 1);
      renderCalendar(currentCalendarDate);
    });
  }
  
  if (nextMonthBtn) {
    nextMonthBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      currentCalendarDate.setMonth(currentCalendarDate.getMonth() + 1);
      renderCalendar(currentCalendarDate);
    });
  }
  
  // Render calendar grid
  function renderCalendar(date) {
    if (!calendarGrid || !monthYearDisplay) return;
    
    const year = date.getFullYear();
    const month = date.getMonth();
    
    monthYearDisplay.textContent = `${date.toLocaleString('de-DE', { month: 'long' })} ${year}`;
    
    // Clear previous calendar
    calendarGrid.innerHTML = '';
    
    // Get first day of month and total days
    const firstDay = new Date(year, month, 1).getDay();
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const adjustedFirstDay = (firstDay === 0) ? 6 : firstDay - 1; // Monday = 0
    
    // Add day headers
    const dayHeaders = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];
    dayHeaders.forEach(day => {
      const header = document.createElement('div');
      header.className = 'calendar-day calendar-day-header';
      header.textContent = day;
      calendarGrid.appendChild(header);
    });
    
    // Add empty cells for days before month starts
    for (let i = 0; i < adjustedFirstDay; i++) {
      const emptyDay = document.createElement('div');
      emptyDay.className = 'calendar-day calendar-day-empty';
      calendarGrid.appendChild(emptyDay);
    }
    
    // Add days of month
    for (let day = 1; day <= daysInMonth; day++) {
      const dayElement = createDayElement(day, month, year);
      calendarGrid.appendChild(dayElement);
    }
  }
  
  function createDayElement(day, month, year) {
    const dayElement = document.createElement('div');
    dayElement.className = 'calendar-day';
    dayElement.textContent = day;
    
    // Check if this is today
    const today = new Date();
    if (day === today.getDate() && month === today.getMonth() && year === today.getFullYear()) {
      dayElement.classList.add('calendar-day-today');
    }
    
    // Check if this is selected date
    if (selectedDate && day === selectedDate.getDate() && month === selectedDate.getMonth() && year === selectedDate.getFullYear()) {
      dayElement.classList.add('calendar-day-selected');
    }
    
    dayElement.addEventListener('click', (e) => {
      e.stopPropagation();
      selectDate(day, month, year);
    });
    
    return dayElement;
  }
  
  function selectDate(day, month, year) {
    selectedDate = new Date(year, month, day);
    if (dateInput) {
      dateInput.value = `${String(day).padStart(2, '0')}.${String(month + 1).padStart(2, '0')}.${year}`;
    }
    
    // Update Cesium clock to selected date
    const currentTime = viewer.clock.currentTime;
    const currentGregorian = Cesium.JulianDate.toGregorianDate(currentTime);
    const newTime = Cesium.JulianDate.fromDate(new Date(year, month, day, currentGregorian.hour, currentGregorian.minute, currentGregorian.second));
    viewer.clock.currentTime = newTime;
    
    if (calendarPopup) {
      calendarPopup.style.display = 'none';
    }
    
    renderCalendar(currentCalendarDate);
  }
  
  // Custom Time Picker
  const timeInput = document.getElementById('customTimeInput');
  const timePopup = document.querySelector('.time-popup');
  const hourDisplay = document.getElementById('hourDisplay');
  const minuteDisplay = document.getElementById('minuteDisplay');
  const hourUpBtn = document.getElementById('hourUp');
  const hourDownBtn = document.getElementById('hourDown');
  const minuteUpBtn = document.getElementById('minuteUp');
  const minuteDownBtn = document.getElementById('minuteDown');
  const setTimeBtn = document.getElementById('setTimeBtn');
  
  let currentHour = 12;
  let currentMinute = 0;
  
  // Toggle time popup
  if (timeInput) {
    timeInput.addEventListener('click', (e) => {
      e.stopPropagation();
      if (timePopup) {
        timePopup.style.display = timePopup.style.display === 'block' ? 'none' : 'block';
        if (timePopup.style.display === 'block') {
          // Initialize with current time
          const currentTime = viewer.clock.currentTime;
          const currentGregorian = Cesium.JulianDate.toGregorianDate(currentTime);
          currentHour = currentGregorian.hour;
          currentMinute = currentGregorian.minute;
          updateTimeDisplay();
        }
      }
    });
  }
  
  // Hour controls
  if (hourUpBtn) {
    hourUpBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      currentHour = (currentHour + 1) % 24;
      updateTimeDisplay();
    });
  }
  
  if (hourDownBtn) {
    hourDownBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      currentHour = (currentHour - 1 + 24) % 24;
      updateTimeDisplay();
    });
  }
  
  // Minute controls
  if (minuteUpBtn) {
    minuteUpBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      currentMinute = (currentMinute + 1) % 60;
      updateTimeDisplay();
    });
  }
  
  if (minuteDownBtn) {
    minuteDownBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      currentMinute = (currentMinute - 1 + 60) % 60;
      updateTimeDisplay();
    });
  }
  
  function updateTimeDisplay() {
    if (hourDisplay) hourDisplay.textContent = String(currentHour).padStart(2, '0');
    if (minuteDisplay) minuteDisplay.textContent = String(currentMinute).padStart(2, '0');
  }
  
  // Set time button
  if (setTimeBtn) {
    setTimeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (timeInput) {
        timeInput.value = `${String(currentHour).padStart(2, '0')}:${String(currentMinute).padStart(2, '0')}`;
      }
      
      // Update Cesium clock to selected time
      const currentTime = viewer.clock.currentTime;
      const currentGregorian = Cesium.JulianDate.toGregorianDate(currentTime);
      const newTime = Cesium.JulianDate.fromDate(new Date(currentGregorian.year, currentGregorian.month - 1, currentGregorian.day, currentHour, currentMinute, 0));
      viewer.clock.currentTime = newTime;
      
      if (timePopup) {
        timePopup.style.display = 'none';
      }
    });
  }
  
  // Close popups when clicking outside
  document.addEventListener('click', (e) => {
    if (calendarPopup && !calendarPopup.contains(e.target) && e.target !== dateInput) {
      calendarPopup.style.display = 'none';
    }
    if (timePopup && !timePopup.contains(e.target) && e.target !== timeInput) {
      timePopup.style.display = 'none';
    }
  });

  // Jump to entered date/time
  const jumpBtn = document.getElementById('jumpToDateTime');
  if (jumpBtn) {
    jumpBtn.addEventListener('click', () => {
      const dateValue = dateInput ? dateInput.value : '';
      const timeValue = timeInput ? timeInput.value : '';
      
      if (dateValue || timeValue) {
        let targetDate = new Date();
        
        // Parse date (DD.MM.YYYY)
        if (dateValue) {
          const dateParts = dateValue.split('.');
          if (dateParts.length === 3) {
            const day = parseInt(dateParts[0], 10);
            const month = parseInt(dateParts[1], 10) - 1;
            const year = parseInt(dateParts[2], 10);
            if (!isNaN(day) && !isNaN(month) && !isNaN(year)) {
              targetDate.setFullYear(year, month, day);
            }
          }
        }
        
        // Parse time (HH:MM)
        if (timeValue) {
          const timeParts = timeValue.split(':');
          if (timeParts.length === 2) {
            const hours = parseInt(timeParts[0], 10);
            const minutes = parseInt(timeParts[1], 10);
            if (!isNaN(hours) && !isNaN(minutes)) {
              targetDate.setHours(hours, minutes, 0);
            }
          }
        }
        
        // Convert to Cesium JulianDate
        const julianDate = Cesium.JulianDate.fromDate(targetDate);
        viewer.clock.currentTime = julianDate;
        
        updateCurrentDateTime();
      }
    });
  }
}
