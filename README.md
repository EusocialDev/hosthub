# Eusocial Voice Agent Dashboard

A modern Django web application for managing and monitoring voice interactions through the Bland.ai API.

## Features

- **Modern UI Design**: Clean, responsive interface with dark header and card-based layout
- **Call Statistics**: Real-time statistics showing completed, abandoned, and in-progress calls
- **Call Management**: View call history, detailed transcripts, and audio recordings
- **Responsive Design**: Mobile-friendly layout that adapts to different screen sizes

## Design Elements

The application features a design inspired by modern dashboard applications:

- **Dark Header**: Professional dark grey header with back navigation
- **Statistics Cards**: Three prominent cards showing call metrics with color-coded icons
- **Two-Column Layout**: Transcription and call history displayed side by side
- **Audio Waveform**: Visual representation of current call audio
- **Branding**: Consistent "eusocial" branding throughout the interface

## Color Scheme

- **Primary Colors**: Dark grey (#212529), white (#ffffff)
- **Accent Colors**: 
  - Green (#8BC34A) for completed calls
  - Orange (#FF9800) for in-progress calls
  - Grey (#6C757D) for abandoned calls
  - Blue (#007bff) for interactive elements

## File Structure

```
testendpoint/
├── static/
│   └── testendpoint/
│       └── css/
│           └── styles.css          # Main stylesheet
├── templates/
│   └── testendpoint/
│       ├── calls.html              # Call list view
│       ├── call_details.html       # Individual call details
│       └── test.html               # Welcome dashboard
└── views.py                        # Backend logic and API integration
```

## Usage

1. **Dashboard**: Visit the main page to see call statistics and quick actions
2. **Call List**: View all calls with status indicators and navigation
3. **Call Details**: Click on any call to see transcripts, recordings, and detailed information
4. **Audio Playback**: Listen to call recordings directly in the browser

## API Integration

The application integrates with Bland.ai API to:
- Fetch call data and statistics
- Retrieve call transcripts and summaries
- Stream audio recordings
- Monitor call status and progress

## Responsive Features

- Mobile-optimized layout
- Flexible grid system
- Touch-friendly navigation
- Adaptive content columns

## Browser Support

- Modern browsers with CSS Grid and Flexbox support
- Audio playback support for MP3 files
- Responsive design for all device sizes
- Call organization based on tags from previous calls
