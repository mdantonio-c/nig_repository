// DO NOT REMOVE ME!
// Put here custom User properties, if any... or keep it empty
export interface CustomUser {}

/**
export interface MyType {
  myfield: string;
  readonly ro: number;
  optional?: Date;
}
**/
export interface Study {
  uuid: string;
  name: string;
  description: string;
  /** counter for existing relationships */
  datasets?: number;
  phenotypes?: number;
  technicals?: number;
}

export interface Studies extends Array<Study> {}
