import { Component, Injector, Input } from "@angular/core";
import { DataService } from "@app/services/data.service";
import { BasePaginationComponent } from "@rapydo/components/base.pagination.component";
import { Phenotype } from "@app/types";

@Component({
  selector: "nig-phenotypes",
  templateUrl: "./phenotypes.component.html"
})
export class PhenotypesComponent extends BasePaginationComponent<Phenotype> {
	@Input() studyUUID;

	constructor(
		protected injector: Injector
	) {
		super(injector);
	}

	ngOnInit() {
		this.init("phenotypes", `study/${this.studyUUID}/phenotypes`, "Phenotypes");
	    this.initPaging(20, false);
	    this.list();
	}

}