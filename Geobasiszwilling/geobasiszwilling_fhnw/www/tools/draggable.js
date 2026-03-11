/**
 * @file tools/draggable.js
 * Makes panels draggable by their drag handle
 */

function makeDraggable(panelId) {
  const panel = document.getElementById(panelId);
  
  if (!panel) return;
  
  let isDragging = false;
  let currentX;
  let currentY;
  let initialX;
  let initialY;
  let xOffset = 0;
  let yOffset = 0;
  
  // Find all drag handles within this panel
  const dragHandles = panel.querySelectorAll('.drag-handle');
  
  dragHandles.forEach(handle => {
    handle.addEventListener('mousedown', dragStart);
  });
  
  document.addEventListener('mousemove', drag);
  document.addEventListener('mouseup', dragEnd);
  
  function dragStart(e) {
    // Only start drag if clicking directly on a drag handle
    if (!e.target.classList.contains('drag-handle')) {
      return;
    }
    
    // Get current position from transform if it exists
    const transform = panel.style.transform;
    if (transform && transform !== 'none') {
      const translateMatch = transform.match(/translate\((.+?)px,\s*(.+?)px\)/);
      if (translateMatch) {
        xOffset = parseFloat(translateMatch[1]) || 0;
        yOffset = parseFloat(translateMatch[2]) || 0;
      } else {
        // Handle translateX only
        const translateXMatch = transform.match(/translateX\((.+?)px\)/);
        if (translateXMatch) {
          xOffset = parseFloat(translateXMatch[1]) || 0;
        }
      }
    }
    
    initialX = e.clientX - xOffset;
    initialY = e.clientY - yOffset;
    
    isDragging = true;
    e.target.style.cursor = 'grabbing';
    panel.style.zIndex = '200'; // Bring to front while dragging
  }
  
  function drag(e) {
    if (isDragging) {
      e.preventDefault();
      
      currentX = e.clientX - initialX;
      currentY = e.clientY - initialY;
      
      xOffset = currentX;
      yOffset = currentY;
      
      // Remove any existing positioning
      panel.style.left = '';
      panel.style.bottom = '';
      
      setTranslate(currentX, currentY, panel);
    }
  }
  
  function dragEnd(e) {
    if (isDragging) {
      initialX = currentX;
      initialY = currentY;
      isDragging = false;
      dragHandles.forEach(handle => {
        handle.style.cursor = 'move';
      });
      panel.style.zIndex = '100'; // Reset z-index
    }
  }
  
  function setTranslate(xPos, yPos, el) {
    el.style.transform = `translate(${xPos}px, ${yPos}px)`;
  }
}

// Initialize draggable panels
function initDraggablePanels() {
  makeDraggable('timelineControls');
  makeDraggable('classificationPanel');
}
