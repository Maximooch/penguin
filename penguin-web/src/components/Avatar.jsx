import PropTypes from 'prop-types';
import './Avatar.css';

const AVATAR_SIZES = {
  message: 40,
  profile: 80
};

function Avatar({ type = 'message', isBot = false, imageUrl = null }) {
  return (
    <div 
      className="avatar-wrapper"
      style={{
        width: `${AVATAR_SIZES[type]}px`,
        height: `${AVATAR_SIZES[type]}px`,
      }}
    >
      <div
        className="avatar"
        style={{
          width: '100%',
          height: '100%',
          backgroundColor: imageUrl ? 'transparent' : '#5865f2',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          overflow: 'hidden',
        }}
      >
        {imageUrl ? (
          <img 
            src={imageUrl} 
            alt="Avatar"
            style={{
              width: '100%',
              height: '100%',
              objectFit: 'cover'
            }}
          />
        ) : (
          <span style={{ color: '#fff', fontWeight: 'bold', fontSize: '16px' }}>
            {isBot ? 'P' : 'U'}
          </span>
        )}
      </div>
      {isBot && <div className="bot-badge">BOT</div>}
    </div>
  );
}

Avatar.propTypes = {
  type: PropTypes.oneOf(['message', 'profile']),
  isBot: PropTypes.bool,
  imageUrl: PropTypes.string
};

export default Avatar; 