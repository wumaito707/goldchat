# Enable Google sign-in for GOLDCHAT

The public GOLDCHAT web client ID is configured in the application release. Both the browser button and the server verifier use the same value. `GOLDCHAT_GOOGLE_CLIENT_ID` can override it when rotating to another web client.

1. Open [Google Auth Platform](https://console.cloud.google.com/auth/overview). Create or select a project named **GOLDCHAT**.
2. If shown, choose **Get started**. Use **GOLDCHAT** as the app name, your support email, and **External** for the audience. Complete the required contact information.
3. Open **Clients → Create client**. Choose **Web application** and name it **GOLDCHAT Web**.
4. Add these **Authorized JavaScript origins**, one per entry:

   - `https://goldchat-app.pages.dev`
   - `https://goldchat-frankfurt.onrender.com`
   - `https://goldchat.onrender.com`

5. This integration uses a JavaScript popup callback. It does not need an authorized redirect URI. Create the client and copy its **Client ID**, ending in `.apps.googleusercontent.com`.
6. The current client ID is included in the deployed application. When replacing it, update the application configuration or set `GOLDCHAT_GOOGLE_CLIENT_ID` in the [Frankfurt Render service environment](https://dashboard.render.com/web/srv-db9uksmq1p3s739ldu90/env) and deploy the updated environment. Apply a replacement ID to the original Render service too if people still use it directly.

The client secret is not used by this integration. Keep it private. Only the public client ID belongs in the configuration above.

After deployment, refresh GOLDCHAT and select **Continue with Google**. Existing password accounts connect Google from **More → Settings → Account recovery**, using the same verified email. Linking never creates or switches to a different account. New Gmail and Google Workspace users can create accounts through Google. Other email providers use GOLDCHAT's email verification first.

If Google requires branding verification, follow the requirements shown in your Google project before opening access to all users. GOLDCHAT requests the basic sign-in profile only.

Reference: [Google Identity Services setup](https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid).
