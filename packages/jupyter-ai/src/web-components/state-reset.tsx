import { useEffect } from 'react';
import { resetRoomState } from './tool-call-card/state';

type StateResetProps = {
  room_id?: string;
};

export function StateReset(props: StateResetProps): null {
  useEffect(() => {
    resetRoomState(props.room_id);
  }, [props.room_id]);

  return null;
}
