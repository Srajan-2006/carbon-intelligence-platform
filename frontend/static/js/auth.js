(function () {
  function showAuthError(el, message) {
    el.textContent = message;
    el.hidden = false;
  }
  function hideAuthError(el) {
    el.hidden = true;
    el.textContent = "";
  }

  const loginForm = document.getElementById("login-form");
  if (loginForm) {
    const errorEl = document.getElementById("auth-error");
    const submitBtn = document.getElementById("login-submit");
    loginForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      hideAuthError(errorEl);
      submitBtn.disabled = true;
      submitBtn.textContent = "Signing In…";
      try {
        await MCI.apiPost("/auth/login", {
          email: document.getElementById("email").value,
          password: document.getElementById("password").value,
        });
        const next = window.MCI_NEXT_URL;
        window.location.href = (next && next.startsWith("/")) ? next : "/";
      } catch (err) {
        showAuthError(errorEl, err.message || "Sign in failed.");
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = "Sign In";
      }
    });
  }

  const registerForm = document.getElementById("register-form");
  if (registerForm) {
    const errorEl = document.getElementById("auth-error");
    const submitBtn = document.getElementById("register-submit");
    registerForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      hideAuthError(errorEl);

      const password = document.getElementById("password").value;
      const confirm = document.getElementById("confirm_password").value;
      if (password !== confirm) {
        showAuthError(errorEl, "Passwords do not match.");
        return;
      }

      submitBtn.disabled = true;
      submitBtn.textContent = "Creating Account…";
      try {
        await MCI.apiPost("/auth/register", {
          name: document.getElementById("name").value,
          email: document.getElementById("email").value,
          role: document.getElementById("role").value,
          mine_id: document.getElementById("mine_id").value,
          password: password,
          confirm_password: confirm,
        });
        window.location.href = "/login";
      } catch (err) {
        showAuthError(errorEl, err.message || "Registration failed.");
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = "Create Account";
      }
    });
  }
})();
