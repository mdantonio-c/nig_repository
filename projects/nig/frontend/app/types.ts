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

export interface Dataset {
  uuid: string;
  name: string;
  description: string;
  files: number;
  technical: number | null;
  phenotype: PhenotypeIdentity;
}

export interface Datasets extends Array<Dataset> {}

export interface PhenotypeIdentity {
  uuid: string;
  name: string;
}

export interface Phenotype extends PhenotypeIdentity {
  birth_place?: string | null;
  birthday: string;
  deathday?: string | null;
  hpo: HPO[];
  sex: string;
}

export interface Phenotypes extends Array<Phenotype> {}

export interface HPO {
  hpo_id: string;
  label: string;
}

export interface TechnicalMetadata {

}

export interface Technicals extends Array<TechnicalMetadata> {}
