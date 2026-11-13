# Move the demo agent to a free Oracle Cloud server

This takes about 30 minutes and costs nothing: everything here uses Oracle's **Always Free** allowance. You need a
browser, a card (Oracle checks it is real but does not charge it), your phone, and your Trading 212 **demo** API key and
secret, which are the ones you already gave the project.

Nothing changes for the agent until the last step. Until then it keeps running on GitHub.

## 1. Create the account (10 min)

1. Go to <https://signup.cloud.oracle.com> and choose **Start for free**.
2. Country: **United Kingdom**. Enter your name and email, then confirm the email.
3. **Home Region: UK South (London).** You cannot change this later.
4. Enter your address and phone number, then the text-message code.
5. Add your card. Oracle places a small temporary hold to check it is real, then releases it.
6. Wait for the "Your account is ready" email, which can take up to 15 minutes, then sign in at
   <https://cloud.oracle.com>.

**Do not** click "Upgrade to Pay As You Go" at any point. A free account cannot be charged.

## 2. Make a sign-in key in Cloud Shell (2 min)

1. In the Oracle console, click the **>_** icon at the top right (**Cloud Shell**). A terminal opens at the bottom of
   the page.
2. Paste this line and press Enter:

   ```
   ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519 <<<y >/dev/null 2>&1; cat ~/.ssh/id_ed25519.pub
   ```

3. It prints one line starting `ssh-ed25519`. Copy the whole line. You need it in the next step.

## 3. Create the server (5 min)

1. Open the menu (≡), then **Compute**, then **Instances**, then **Create instance**.
2. Name: `market-agent`.
3. **Image and shape**, then **Edit**:
   - Image: click **Change image** and pick **Canonical Ubuntu 24.04**. The normal one is fine; you do not need the
     "Minimal" one.
   - Shape: click **Change shape**, choose **Ampere**, then **VM.Standard.A1.Flex**. Set **1 OCPU** and **6 GB**
     memory. It must show the **Always Free-eligible** label.
4. **Add SSH keys**: choose **Paste public keys** and paste the line from step 2.
5. Leave everything else as it is and click **Create**.
6. When it turns green (**Running**), copy the **Public IP address** from the instance page.

If Oracle says **"Out of capacity"** for Ampere in London, that is common. You have two options:

- Try again in a few hours.
- Choose the shape **VM.Standard.E2.1.Micro** (AMD) instead. It is also Always Free, and the setup adds the memory
  it needs.

## 4. Run the setup (10 min)

1. In Cloud Shell, connect to the server. Put your server's IP in place of `IP`:

   ```
   ssh ubuntu@IP
   ```

   Type `yes` if it asks about the fingerprint.
2. Paste this one command:

   ```
   curl -fsSL https://raw.githubusercontent.com/GreensideComps/agent-skills/master/ops/market-agent-host/vm/setup.sh | sudo bash
   ```

3. Partway through, it stops and shows one long line starting `ssh-ed25519 ... market-agent-vm`. This line lets the
   server save the agent's encrypted state to your GitHub repository:
   - open <https://github.com/GreensideComps/agent-skills/settings/keys/new>
   - Title: `oracle-vm`. Key: paste that line. Tick **Allow write access**. Click **Add key**.
   - go back to Cloud Shell and press Enter.
4. It asks for your **Trading 212 demo API key**, then the **secret**. Paste each one and press Enter. Nothing
   shows while you paste, which is normal. The setup checks them against the demo account and stores them only on the
   server.
5. It finishes with **"Done. The server is set up and standing by"**.

## 5. Tell Claude

Write "the server is ready" in the project. Claude then:

- re-encrypts the agent's saved state for the new server;
- hands trading over to it. The GitHub copy stops by itself within 2 minutes, and the server picks up where it left
  off;
- watches it for a day, then switches the GitHub copy off.

If anything goes wrong, Claude can hand trading straight back to GitHub with one command, and no state is lost.

## Good to know

- The server runs the agent in **demo mode only**. The setup refuses a key that the demo API does not accept.
- Oracle can reclaim an Always Free server that looks idle for 7 days (low CPU, network and memory use). The agent
  is light, so this could happen. If it does, the system's outage alert fires, Claude hands trading back to GitHub
  with no state lost, and you can redo step 3 and step 4, or stay on GitHub.
- To look at it yourself: in Cloud Shell, `ssh ubuntu@IP`, then `sudo systemctl status market-agent`.
