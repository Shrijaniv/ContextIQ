# UI Customization Guide

This guide shows you how to customize the voice agent UI to match your brand and requirements.

## Table of Contents

- [About the UI](#about-the-ui)
- [Quick Customization Examples](#quick-customization-examples)
- [Cloudscape Resources](#cloudscape-resources)
- [Key UI Features](#key-ui-features)

---

## About the UI

The frontend is built with [AWS Cloudscape Design System](https://cloudscape.design/), AWS's open-source design system for building intuitive web applications. While AgentCore is the focus of this demo, the UI is designed to be easily customizable.

### Why Cloudscape?

- **AWS Native**: Built by AWS for AWS applications
- **Accessibility**: WCAG 2.1 AA compliant out of the box
- **Responsive**: Works seamlessly across devices
- **Rich Components**: 50+ pre-built components for common patterns
- **GenAI Patterns**: Specialized components for AI chat interfaces

---

## Quick Customization Examples

### 1. Change Support Prompts

Edit `frontend/src/App.tsx` and modify the `getSupportPrompts()` function:

```typescript
const getSupportPrompts = () => {
  if (messages.length === 0) {
    return [
      { id: 'custom1', text: 'Your custom prompt here' },
      { id: 'custom2', text: 'Another custom prompt' },
      { id: 'custom3', text: 'Third custom prompt' },
      // Add more prompts...
    ];
  }
  
  // Add contextual prompts based on conversation
  return [
    { id: 'followup1', text: 'Tell me more about that' },
    { id: 'followup2', text: 'Can you explain differently?' },
  ];
};
```

### 2. Change Prompt Alignment

Switch between horizontal and vertical layout:

```typescript
<SupportPromptGroup
  alignment="horizontal"  // or "vertical"
  items={getSupportPrompts()}
  onPromptClick={handlePromptClick}
/>
```

### 3. Customize Markdown Styling

Edit `frontend/src/markdown.css` to change how agent responses look:

```css
/* Change code block background */
.markdown-content pre {
  background-color: #f0f0f0;
  border-radius: 8px;
  padding: 16px;
}

/* Customize table styling */
.markdown-content table th {
  background-color: #e0e0e0;
  font-weight: bold;
}

/* Change link colors */
.markdown-content a {
  color: #0073bb;
  text-decoration: underline;
}

/* Customize list styling */
.markdown-content ul {
  list-style-type: square;
}
```

### 4. Add More Feedback Options

In `frontend/src/App.tsx`, find the ButtonGroup items array and add new buttons:

```typescript
{
  type: 'icon-button',
  id: 'share',
  iconName: 'share',
  text: 'Share',
}
```

Then handle the click event:

```typescript
const handleFeedback = (detail: { id: string }) => {
  if (detail.id === 'share') {
    // Implement share functionality
    navigator.clipboard.writeText(message.content);
    console.log('Message shared!');
  }
  // ... other feedback handlers
};
```

### 5. Change App Theme Colors

Cloudscape uses design tokens for theming. Create `frontend/src/theme.css`:

```css
:root {
  /* Primary colors */
  --awsui-color-text-heading-default: #232f3e;
  --awsui-color-background-container-content: #ffffff;
  
  /* Accent colors */
  --awsui-color-text-accent: #0073bb;
  --awsui-color-background-button-primary-default: #ec7211;
  
  /* Status colors */
  --awsui-color-text-status-success: #037f0c;
  --awsui-color-text-status-error: #d13212;
  
  /* Spacing */
  --awsui-space-scaled-m: 16px;
  --awsui-space-scaled-l: 24px;
}
```

Then import it in `frontend/src/main.tsx`:

```typescript
import './theme.css';
```

### 6. Customize Chat Bubble Appearance

Edit the ChatBubble component usage in `frontend/src/App.tsx`:

```typescript
<ChatBubble
  type={message.role === 'user' ? 'outgoing' : 'incoming'}
  avatar={
    message.role === 'user' ? (
      <Avatar
        ariaLabel="User"
        iconName="user-profile"
        color="gen-ai"  // Change color: gen-ai, blue, red, green, etc.
      />
    ) : (
      <Avatar
        ariaLabel="Agent"
        iconName="gen-ai"
        color="blue"  // Customize agent avatar color
      />
    )
  }
>
  {/* Message content */}
</ChatBubble>
```

### 7. Add Custom Header

Replace the default header in `frontend/src/App.tsx`:

```typescript
<TopNavigation
  identity={{
    href: '#',
    title: 'Your Company Name',  // Customize title
    logo: {
      src: '/your-logo.png',  // Add your logo
      alt: 'Your Company Logo',
    },
  }}
  utilities={[
    {
      type: 'button',
      text: user?.email || 'Sign In',
      onClick: () => setShowAuthModal(true),
    },
  ]}
/>
```

### 8. Customize Loading States

Change the loading indicator in `frontend/src/App.tsx`:

```typescript
{isAgentSpeaking && (
  <Box textAlign="center" padding="s">
    <Spinner size="large" />  {/* Change size: small, normal, large */}
    <Box variant="p" color="text-status-info">
      Agent is thinking...  {/* Customize message */}
    </Box>
  </Box>
)}
```

### 9. Add Status Indicators

Show connection status with custom styling:

```typescript
<StatusIndicator type={
  connectionStatus === 'connected' ? 'success' :
  connectionStatus === 'connecting' ? 'in-progress' :
  'error'
}>
  {connectionStatus === 'connected' ? 'Connected' :
   connectionStatus === 'connecting' ? 'Connecting...' :
   'Disconnected'}
</StatusIndicator>
```

### 10. Customize Voice Controls

Modify the voice control buttons:

```typescript
<Button
  variant="primary"
  iconName={isRecording ? 'microphone-off' : 'microphone'}
  onClick={toggleRecording}
  disabled={connectionStatus !== 'connected'}
>
  {isRecording ? 'Stop Speaking' : 'Start Speaking'}
</Button>
```

---

## Cloudscape Resources

### Official Documentation

- [Component Library](https://cloudscape.design/components/) - Browse all 50+ components
- [GenAI Chat Patterns](https://cloudscape.design/patterns/genai/generative-AI-chat/) - Best practices for AI chat interfaces
- [Design Tokens](https://cloudscape.design/foundation/visual-foundation/design-tokens/) - Complete list of customizable tokens
- [GitHub Repository](https://github.com/cloudscape-design/components) - Source code and examples

### Useful Components for Voice Agents

- **ChatBubble**: Display user and agent messages
- **Avatar**: User and agent profile pictures
- **SupportPromptGroup**: Suggested prompts/questions
- **StatusIndicator**: Show connection status
- **Button**: Voice controls, actions
- **Spinner**: Loading states
- **Alert**: Error messages, notifications
- **TopNavigation**: App header with branding
- **Box**: Layout and spacing
- **Grid**: Responsive layouts

---

## Key UI Features in This Demo

### Chat Components

- **ChatBubble**: Displays messages with markdown support
- **Avatar**: Shows user/agent icons with customizable colors
- **SupportPromptGroup**: Suggested prompts that change based on context

### Markdown Rendering

- Full markdown support with `react-markdown`
- Code syntax highlighting
- Tables, lists, links
- Custom styling via `markdown.css`

### Feedback Buttons

- Thumbs up/down for message rating
- Copy button to copy message content
- Extensible for additional actions (share, bookmark, etc.)

### Authentication UI

- Sign in/sign up modal with Cognito
- Email verification flow
- Password strength requirements
- Error handling and validation

### Responsive Layout

- 3-column grid that adapts to screen size
- Mobile-friendly design
- Proper spacing and alignment
- Accessible keyboard navigation

### Design Tokens

- Consistent styling using Cloudscape tokens
- Easy theme customization
- Dark mode support (via Cloudscape)
- Responsive spacing and sizing

---

## Advanced Customization

### Adding New Pages

To add additional pages (settings, history, etc.):

1. Create new component in `frontend/src/components/`
2. Add routing with React Router
3. Update TopNavigation with new menu items

### Custom Audio Visualization

Replace the simple loading bar with a custom audio visualizer:

```typescript
// Create frontend/src/components/AudioVisualizer.tsx
import { useEffect, useRef } from 'react';

export function AudioVisualizer({ audioContext, stream }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  
  useEffect(() => {
    if (!audioContext || !stream) return;
    
    const analyser = audioContext.createAnalyser();
    const source = audioContext.createMediaStreamSource(stream);
    source.connect(analyser);
    
    // Implement visualization logic
    // Draw waveform or frequency bars on canvas
  }, [audioContext, stream]);
  
  return <canvas ref={canvasRef} width={300} height={100} />;
}
```

### Internationalization (i18n)

Add multi-language support:

1. Install i18n library: `npm install react-i18next i18next`
2. Create translation files in `frontend/src/locales/`
3. Wrap app with i18n provider
4. Use translation keys in components

### Persistent Settings

Store user preferences in localStorage:

```typescript
// Save settings
localStorage.setItem('voiceSettings', JSON.stringify({
  autoStart: true,
  volume: 0.8,
  theme: 'light',
}));

// Load settings
const settings = JSON.parse(localStorage.getItem('voiceSettings') || '{}');
```

---

## Testing Your Changes

### Local Development

After making UI changes, test locally:

```powershell
# Start local development server
.\dev-local.ps1

# Frontend will hot-reload on changes
# Open http://localhost:5173
```

### Build and Deploy

When ready to deploy your changes:

```powershell
# Get stack outputs
$agentRuntimeArn = aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiRuntime --query "Stacks[0].Outputs[?OutputKey=='AgentRuntimeArn'].OutputValue" --output text --no-cli-pager
$region = aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiRuntime --query "Stacks[0].Outputs[?OutputKey=='Region'].OutputValue" --output text --no-cli-pager
$userPoolId = aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiAuth --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text --no-cli-pager
$userPoolClientId = aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiAuth --query "Stacks[0].Outputs[?OutputKey=='UserPoolClientId'].OutputValue" --output text --no-cli-pager
$identityPoolId = aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiAuth --query "Stacks[0].Outputs[?OutputKey=='IdentityPoolId'].OutputValue" --output text --no-cli-pager

# Build and deploy
.\scripts\build-frontend.ps1 -UserPoolId $userPoolId -UserPoolClientId $userPoolClientId -IdentityPoolId $identityPoolId -AgentRuntimeArn $agentRuntimeArn -Region $region
cd cdk
npx cdk deploy AgentCoreNovaSonicBidiFrontend --no-cli-pager
```

---

## Common Customization Patterns

### Branding

1. Replace logo in TopNavigation
2. Update color scheme with design tokens
3. Customize fonts (add to `index.css`)
4. Update favicon and app title

### User Experience

1. Add keyboard shortcuts
2. Implement voice commands
3. Add conversation history
4. Enable conversation export

### Functionality

1. Add file upload for documents
2. Implement conversation search
3. Add user preferences panel
4. Enable conversation sharing

---

## Need Help?

- Check [Cloudscape documentation](https://cloudscape.design/)
- Review [example implementations](https://github.com/cloudscape-design/components/tree/main/pages)
- Ask questions in [Cloudscape GitHub discussions](https://github.com/cloudscape-design/components/discussions)
