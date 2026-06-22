(function () {
  const screen = document.querySelector("[data-clock-screen]");
  if (!screen) {
    return;
  }

  const clockInButton = document.getElementById("clock-in-btn");
  const clockOutButton = document.getElementById("clock-out-btn");
  const clockInTime = document.getElementById("clock-in-time");
  const clockOutTime = document.getElementById("clock-out-time");
  const message = document.getElementById("clock-message");
  const weeklyLogContainer = document.getElementById("weekly-log-container");

  const state = {
    inSession: clockInButton.classList.contains("disabled"),
    submitting: false,
  };

  function formatCurrentTime() {
    return new Date().toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });
  }

  function updateButtonTimes() {
    const now = formatCurrentTime();
    clockInTime.textContent = `Clock In · ${now}`;
    clockOutTime.textContent = `Clock Out · ${now}`;
  }

  function setButtonState() {
    const clockInDisabled = state.inSession;
    const clockOutDisabled = !state.inSession;

    clockInButton.disabled = clockInDisabled || state.submitting;
    clockOutButton.disabled = clockOutDisabled || state.submitting;

    clockInButton.classList.toggle("disabled", clockInDisabled);
    clockOutButton.classList.toggle("disabled", clockOutDisabled);
  }

  function runPulse(button, className) {
    button.classList.remove(className);
    void button.offsetWidth;
    button.classList.add(className);
    window.setTimeout(() => {
      button.classList.remove(className);
    }, 500);
  }

  function setMessage(text, isError) {
    message.textContent = text;
    message.classList.toggle("clock-message-error", Boolean(isError));
  }

  async function submitClockAction(action) {
    if (state.submitting) {
      return;
    }

    state.submitting = true;
    setButtonState();
    setMessage("", false);

    try {
      const response = await fetch(`/student/${action}`, {
        method: "POST",
      });
      const payload = await response.json();

      if (!response.ok) {
        setMessage("Couldn't record punch. Try again.", true);
        return;
      }

      if (!payload.success) {
        if (payload.error === "already_clocked_in") {
          setMessage(payload.message || `Already clocked in at ${payload.time}.`, true);
        } else if (payload.error === "not_clocked_in") {
          setMessage("Not clocked in.", true);
        } else {
          setMessage("Couldn't record punch. Try again.", true);
        }
        return;
      }

      if (action === "clock-in") {
        runPulse(clockInButton, "pulse-in");
        state.inSession = true;
        setMessage(payload.message || `Clocked in at ${payload.time}`, false);
      } else {
        runPulse(clockOutButton, "pulse-out");
        state.inSession = false;
        setMessage(payload.message || `Clocked out — ${payload.duration} session`, false);
      }

      await refreshWeeklyLog();
    } catch (_) {
      setMessage("Couldn't record punch. Try again.", true);
    } finally {
      state.submitting = false;
      setButtonState();
    }
  }

  async function refreshWeeklyLog() {
    if (!weeklyLogContainer) {
      return;
    }

    try {
      const response = await fetch("/student/clock/log", { method: "GET" });
      if (!response.ok) {
        return;
      }
      weeklyLogContainer.innerHTML = await response.text();
    } catch (_) {
      // Leave existing log visible on refresh errors.
    }
  }

  clockInButton.addEventListener("click", () => {
    submitClockAction("clock-in");
  });

  clockOutButton.addEventListener("click", () => {
    submitClockAction("clock-out");
  });

  setButtonState();
  updateButtonTimes();
  window.setInterval(updateButtonTimes, 30000);
})();
