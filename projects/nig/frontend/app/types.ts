// DO NOT REMOVE ME!
// Put here custom User properties, if any... or keep it empty
export interface CustomUser {}

export interface Study {
  uuid: string;
  name: string;
  description: string;
  /** counter for existing relationships */
  /** @nullable */
  datasets?: number;
  /** @nullable */
  phenotypes?: number;
  /** @nullable */
  technicals?: number;
}

export interface Studies extends Array<Study> {}

export interface Dataset {
  uuid: string;
  name: string;
  description: string;
  files: number;
  /** @nullable */
  technical?: number;
  /** @nullable */
  phenotype: PhenotypeIdentity;
}

export interface Datasets extends Array<Dataset> {}

export interface PhenotypeIdentity {
  uuid: string;
  name: string;
}

export interface Phenotype extends PhenotypeIdentity {
  /** @nullable */
  birth_place?: string;
  /** @nullable */
  birthday?: string;
  /** @nullable */
  deathday?: string;
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
