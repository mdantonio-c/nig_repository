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

export interface Dataset extends ResourceIdentity {
  description: string;
  files: number;
  /** @nullable */
  technical?: number;
  /** @nullable */
  phenotype: ResourceIdentity;
}

export interface Datasets extends Array<Dataset> {}

export interface ResourceIdentity {
  uuid: string;
  name: string;
}

export interface Phenotype extends ResourceIdentity {
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

export interface TechnicalMetadata extends ResourceIdentity {
  /** @nullable */
  sequencing_date: string;
  /** @nullable */
  platform: string;
  /** @nullable */
  enrichment_kit: string;
}

export interface Technicals extends Array<TechnicalMetadata> {}
