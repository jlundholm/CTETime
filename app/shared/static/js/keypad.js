(function () {
  const root = document.querySelector("[data-student-login]");
  if (!root) {
    return;
  }

  const pinDisplay = document.getElementById("pin-display");
  const errorMessage = document.getElementById("error-message");
  const guidanceMessage = document.getElementById("guidance-message");
  const enterButton = root.querySelector('[data-action="enter"]');
  const keypadButtons = root.querySelectorAll(".keypad-key");

  const state = {
    digits: [],
    masked: [],
    failedAttempts: 0,
    submitting: false,
    maskTimers: [],
  };

  function renderDisplay() {
    const value = state.digits
      .map((digit, index) => (state.masked[index] ? "•" : digit))
      .join("");
    pinDisplay.value = value;
    enterButton.disabled = state.digits.length !== 6 || state.submitting;
  }

  function clearMaskTimers() {
    state.maskTimers.forEach((timerId) => clearTimeout(timerId));
    state.maskTimers = [];
  }

  function clearInput() {
    clearMaskTimers();
    state.digits = [];
    state.masked = [];
    state.submitting = false;
    renderDisplay();
  }

  function clearMessages() {
    errorMessage.textContent = "";
    guidanceMessage.textContent = "";
    pinDisplay.classList.remove("pin-input-error");
  }

  function addDigit(digit) {
    if (state.digits.length >= 6 || state.submitting) {
      return;
    }

    clearMessages();
    state.digits.push(digit);
    state.masked.push(false);
    renderDisplay();

    const index = state.digits.length - 1;
    const timerId = window.setTimeout(() => {
      state.masked[index] = true;
      renderDisplay();
    }, 1000);
    state.maskTimers.push(timerId);

    if (state.digits.length === 6) {
      submitPin();
    }
  }

  function removeDigit() {
    if (state.submitting) {
      return;
    }
    const timerId = state.maskTimers.pop();
    clearTimeout(timerId);
    state.digits.pop();
    state.masked.pop();
    renderDisplay();
  }

  function handleFailure(payload) {
    state.failedAttempts = payload.failures ?? state.failedAttempts + 1;
    pinDisplay.classList.add("pin-input-error");

    if (state.failedAttempts >= 3) {
      guidanceMessage.textContent = "See your teacher for your PIN.";
      errorMessage.textContent = payload.error || "Incorrect PIN.";
    } else {
      errorMessage.textContent = payload.error || "Incorrect PIN.";
      guidanceMessage.textContent = "";
    }
    clearInput();
  }

  async function submitPin() {
    if (state.digits.length !== 6 || state.submitting) {
      return;
    }

    state.submitting = true;
    renderDisplay();

    const pin = state.digits.join("");
    const body = new URLSearchParams({ pin }).toString();

    try {
      const response = await fetch("/auth/student/login", {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body,
      });
      const payload = await response.json();

      if (payload.success) {
        window.location.href = payload.redirect;
        return;
      }

      handleFailure(payload);
    } catch (_) {
      errorMessage.textContent = "Unable to sign in. Please try again.";
      pinDisplay.classList.add("pin-input-error");
      clearInput();
    }
  }

  keypadButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const digit = button.getAttribute("data-key");
      const action = button.getAttribute("data-action");

      if (digit !== null) {
        addDigit(digit);
        return;
      }

      if (action === "backspace") {
        removeDigit();
        return;
      }

      if (action === "enter") {
        submitPin();
      }
    });
  });

  renderDisplay();
})();
